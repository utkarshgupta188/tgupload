from __future__ import annotations
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import AsyncIterator
import asyncio
import tempfile
import os
import httpx

from .config import settings
from .auth import require_auth
from .db import init_db, get_db, File as DBFile
from .telegram import tg_client

app = FastAPI(title="TG Cloud Storage")

# CORS: allow all by default or from BASE_URL
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.BASE_URL else [str(settings.BASE_URL)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def on_startup():
    init_db()
    # Validate required env settings based on mode
    mode = settings.TELEGRAM_UPLOAD_MODE
    if mode == "bot":
        if not (settings.TELEGRAM_BOT_TOKEN and settings.TG_CHAT_ID):
            raise RuntimeError("Bot mode requires TELEGRAM_BOT_TOKEN and TG_CHAT_ID")
    elif mode == "user":
        if not (settings.TG_API_ID and settings.TG_API_HASH and settings.TG_SESSION_STRING and settings.TG_CHAT_ID):
            raise RuntimeError("User mode requires TG_API_ID, TG_API_HASH, TG_SESSION_STRING, TG_CHAT_ID")

@app.on_event("shutdown")
async def on_shutdown():
    await tg_client.close()


@app.get("/api/health")
async def health(auth=Depends(require_auth)):
    return {"status": "ok"}


@app.get("/api/diagnostics/resolve_chat")
async def diagnostics_resolve_chat(auth=Depends(require_auth)):
    """Resolve TG_CHAT_ID and report the user identity (user mode only)."""
    if settings.TELEGRAM_UPLOAD_MODE != "user":
        raise HTTPException(status_code=400, detail="Diagnostics available only in user mode")
    try:
        # Access underlying client
        await tg_client.start()
        me = await tg_client.client.get_me()
        # Resolve chat
        # Use helper to resolve peer
        peer = await tg_client._resolve_peer(settings.TG_CHAT_ID)  # type: ignore[attr-defined]
        chat = await tg_client.client.get_chat(peer)
        return {
            "me": {"id": getattr(me, "id", None), "username": getattr(me, "username", None), "phone": getattr(me, "phone_number", None)},
            "chat": {"id": getattr(chat, "id", None), "title": getattr(chat, "title", None), "username": getattr(chat, "username", None)},
            "peer_used": peer,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to resolve chat: {e}")


@app.post("/api/upload")
async def upload_file(
    auth=Depends(require_auth),
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Upload size limits differ by mode
    MAX_BOT_UPLOAD = 50 * 1024 * 1024  # 50 MB (bot)

    filename = upload.filename or "file"
    content_type = upload.content_type
    # Persist to a temp file to avoid buffering whole upload in memory while enforcing 2GB limit
    total = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            # Bound the total time spent receiving the body to avoid infinite hangs
            recv_timeout = int(settings.UPLOAD_TIMEOUT_SECONDS or 1800)
            deadline = asyncio.get_event_loop().time() + recv_timeout
            while True:
                # Adjust per-chunk timeout to remaining time budget
                remaining = max(1.0, deadline - asyncio.get_event_loop().time())
                chunk = await asyncio.wait_for(upload.read(1024 * 1024), timeout=remaining)
                if not chunk:
                    break
                total += len(chunk)
                if settings.TELEGRAM_UPLOAD_MODE == "bot" and total > MAX_BOT_UPLOAD:
                    raise HTTPException(status_code=413, detail=f"File exceeds Telegram Bot API limit of 50 MB (got {total//(1024*1024)} MB)")
                tmp.write(chunk)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            result = await tg_client.send_document_file(
                chat_id=settings.TG_CHAT_ID,
                filename=filename,
                file_obj=f,
                content_type=content_type,
            )
    except httpx.HTTPStatusError as e:
        # Surface Telegram response body if available
        body = None
        try:
            body = e.response.text
        except Exception:
            body = str(e)
        raise HTTPException(status_code=502, detail=f"Telegram error {e.response.status_code}: {body}")
    except httpx.HTTPError as e:
        # Other HTTP transport error
        raise HTTPException(status_code=502, detail=f"Telegram transport error: {e}")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Upload timed out (increase UPLOAD_TIMEOUT_SECONDS)")
    except Exception as e:
        # Any unexpected error
        msg = str(e)
        if settings.TELEGRAM_UPLOAD_MODE == "user" and ("Peer id invalid" in msg or "chat" in msg.lower()):
            raise HTTPException(status_code=400, detail=f"Upload failed: invalid TG_CHAT_ID or user not in chat. Ensure the user session has access to TG_CHAT_ID='{settings.TG_CHAT_ID}'. Details: {msg}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {msg}")
    finally:
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    # result["document"]["file_id"]
    doc = result.get("document") or {}
    tg_file_id = doc.get("file_id")
    file_size = doc.get("file_size") or total
    chat_id = result.get("chat_id") or (result.get("chat", {}) or {}).get("id")
    message_id = result.get("message_id")

    if not tg_file_id and settings.TELEGRAM_UPLOAD_MODE == "bot":
        raise HTTPException(status_code=500, detail="Telegram upload failed")

    db_item = DBFile(
        tg_file_id=tg_file_id or str(message_id or ""),
        name=filename,
        size=file_size,
        chat_id=str(chat_id) if chat_id is not None else None,
        message_id=message_id,
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)

    return {"id": db_item.id, "file_id": tg_file_id, "name": filename, "size": file_size}


@app.get("/api/files")
async def list_files(
    auth=Depends(require_auth),
    q: str | None = Query(default=None, description="Search by name contains"),
    db: Session = Depends(get_db),
):
    query = db.query(DBFile)
    if q:
        # Use LIKE with lower() for portability across SQLite/Postgres
        query = query.filter(DBFile.name.ilike(f"%{q}%") if hasattr(DBFile.name, 'ilike') else (DBFile.name.like(f"%{q}%")))
    rows = query.order_by(DBFile.id.desc()).all()
    return [
        {"id": r.id, "file_id": r.tg_file_id, "name": r.name, "size": r.size}
        for r in rows
    ]


@app.get("/api/download/{file_id}")
async def download_file(file_id: str, request: Request, auth=Depends(require_auth)):
    # Resolve file path via getFile then stream from Telegram CDN through this server
    if settings.TELEGRAM_UPLOAD_MODE == "bot":
        try:
            meta = await tg_client.get_file(file_id)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=404, detail=str(e))
        file_path = meta.get("file_path")
        if not file_path:
            raise HTTPException(status_code=404, detail="Not found on Telegram")

        url = tg_client.file_url(file_path)

        async def iter_cdn():
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                        yield chunk

        stream = iter_cdn()
        response = StreamingResponse(stream, media_type="application/octet-stream")
        filename = file_path.split("/")[-1]
        response.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\""
        size = meta.get("file_size")
        if size:
            response.headers["Content-Length"] = str(size)
        return response
    else:
        # User mode: download via Pyrogram using stored chat_id/message_id
        db = next(get_db())
        row = (
            db.query(DBFile)
            .filter((DBFile.tg_file_id == file_id) | (DBFile.id == (int(file_id) if file_id.isdigit() else -1)))
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        has_msg_ref = (row.chat_id is not None) and (row.message_id is not None)

        # Download to temp path then stream back
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp_path = tmp.name
            tmp.close()
            if has_msg_ref:
                # Use message reference
                # Lazily import pyrogram client instance via tg_client
                assert row.chat_id is not None and row.message_id is not None
                chat_id_int = int(str(row.chat_id))
                message_id_int = int(row.message_id)
                msg = await tg_client.client.get_messages(chat_id_int, message_id_int)
                out_path = await tg_client.client.download_media(msg, file_name=tmp_path)
            else:
                out_path = await tg_client.download_temp_by_file_id(row.tg_file_id)
                tmp_path = out_path
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Telegram download failed: {e}")

        async def iter_file():
            try:
                with open(tmp_path, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 64)
                        if not chunk:
                            break
                        yield chunk
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

        response = StreamingResponse(iter_file(), media_type="application/octet-stream")
        response.headers["Content-Disposition"] = f"attachment; filename=\"{row.name}\""
        if row.size:
            response.headers["Content-Length"] = str(row.size)
        return response
