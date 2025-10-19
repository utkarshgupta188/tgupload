from __future__ import annotations

import importlib
import tempfile
from typing import Optional, IO, Any

import httpx
import asyncio

from .config import settings

BASE = "https://api.telegram.org"


class BotTelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"{BASE}/bot{token}"
        self.file_base = f"{BASE}/file/bot{token}"
        # Use configurable timeouts for large files and slower networks
        t = float(settings.TELEGRAM_HTTP_TIMEOUT_SECONDS or 300)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(t, connect=t, read=t))

    async def close(self):
        await self.client.aclose()

    async def send_document_file(
        self,
        chat_id: int | str,
        filename: str,
        file_obj: IO[bytes],
        content_type: Optional[str] = None,
    ) -> dict:
        files = {"document": (filename, file_obj, content_type or "application/octet-stream")}
        data = {"chat_id": str(chat_id)}
        url = f"{self.base_url}/sendDocument"
        resp = await self.client.post(url, data=data, files=files)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise httpx.HTTPError(f"Telegram API error: {payload}")
        return payload["result"]

    async def get_file(self, file_id: str) -> dict:
        url = f"{self.base_url}/getFile"
        resp = await self.client.get(url, params={"file_id": file_id})
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise httpx.HTTPError(f"Telegram API error: {payload}")
        return payload["result"]

    def file_url(self, file_path: str) -> str:
        return f"{self.file_base}/{file_path}"


class UserTelegramClient:
    def __init__(self, api_id: int, api_hash: str, session_string: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.client: Any = None
        self._started = False

    async def start(self):
        if not self._started:
            pyrogram = importlib.import_module("pyrogram")
            Client = getattr(pyrogram, "Client")
            self.client = Client(
                name="user_session",
                api_id=self.api_id,
                api_hash=self.api_hash,
                session_string=self.session_string,
            )
            await self.client.start()
            # Best-effort: auto-join target chat if a username or invite link is provided
            try:
                chat_ident = settings.TG_CHAT_ID
                if isinstance(chat_ident, str) and chat_ident:
                    s = chat_ident.strip()
                    if s.startswith("@") or s.startswith("https://t.me/") or "joinchat" in s or "tg://join" in s:
                        await self.client.join_chat(s)
            except Exception:
                # Ignore if can't join automatically; user may already be a member or using a numeric id
                pass
            self._started = True

    async def close(self):
        if self._started and self.client is not None:
            await self.client.stop()
            self._started = False

    async def send_document_file(
        self,
        chat_id: int | str,
        filename: str,
        file_obj: IO[bytes],
        content_type: Optional[str] = None,
    ) -> dict:
        await self.start()
        path = getattr(file_obj, "name", None)
        if not path:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(file_obj.read())
                path = tmp.name
        peer = await self._resolve_peer(chat_id)
        # Add a generous timeout to avoid hanging indefinitely
        timeout_s = int(settings.UPLOAD_TIMEOUT_SECONDS or 1800)
        msg = await asyncio.wait_for(
            self.client.send_document(peer, document=path, file_name=filename),
            timeout=timeout_s,
        )
        doc = getattr(msg, "document", None)
        chat = getattr(msg, "chat", None)
        return {
            "message_id": getattr(msg, "id", None),
            "chat_id": getattr(chat, "id", None),
            "document": {
                "file_name": filename,
                "file_size": getattr(doc, "file_size", None) if doc else None,
                "file_id": getattr(doc, "file_id", None) if doc else None,
            },
        }

    async def download_temp_by_file_id(self, file_id: str) -> str:
        await self.start()
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        out = await self.client.download_media(file_id, file_name=tmp_path)
        return out or tmp_path

    @staticmethod
    def _normalize_peer(val: int | str) -> int | str:
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            s = val.strip()
            # Keep numeric strings (including -100...) as strings; Pyrogram can resolve via get_chat
            # Also allow '@username' or invite links as-is
            return s
        return val

    async def _resolve_peer(self, chat_id: int | str) -> int | str:
        """Resolve chat identifier to a form Pyrogram can send to.
        - If numeric-like, convert to int and verify accessibility via get_chat.
        - If @username or link, return as-is (Pyrogram will resolve) and try join on failure.
        """
        peer = self._normalize_peer(chat_id)
        try:
            # Try to resolve to ensure it's valid and we have access
            chat = await self.client.get_chat(peer)
            return chat.id if getattr(chat, "id", None) is not None else peer
        except Exception:
            # Retry with int if it's a numeric-looking string (-100...)
            if isinstance(peer, str):
                s = peer.strip()
                if (s and (s[0] == '-' and s[1:].isdigit() or s.isdigit())):
                    try:
                        chat = await self.client.get_chat(int(s))
                        return chat.id if getattr(chat, "id", None) is not None else int(s)
                    except Exception:
                        pass
            # If it's a username/link, attempt join once and retry
            try:
                if isinstance(peer, str) and (peer.startswith("@") or peer.startswith("https://t.me/")):
                    await self.client.join_chat(peer)
                    chat = await self.client.get_chat(peer)
                    return chat.id if getattr(chat, "id", None) is not None else peer
            except Exception:
                pass
            # Last resort: return peer; send may still fail but error will bubble with clearer context
            return peer


# Factory: create the appropriate client based on settings
tg_client: Any
if settings.TELEGRAM_UPLOAD_MODE == "user":
    tg_client = UserTelegramClient(int(settings.TG_API_ID or 0), str(settings.TG_API_HASH or ""), str(settings.TG_SESSION_STRING or ""))
else:
    tg_client = BotTelegramClient(str(settings.TELEGRAM_BOT_TOKEN or ""))
