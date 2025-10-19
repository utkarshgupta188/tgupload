from fastapi import Header, HTTPException, status, Depends, Request
from .config import settings

API_HEADER = "X-API-KEY"

async def verify_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API password not configured")
    if x_api_key != settings.API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


# Also support Bearer token
async def verify_bearer(authorization: str | None = Header(default=None)):
    if not settings.API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API password not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    if token != settings.API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")


# A convenience dependency that accepts either header
async def require_auth(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
):
    if not settings.API_PASSWORD:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API password not configured")
    if x_api_key == settings.API_PASSWORD:
        return True
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        if token == settings.API_PASSWORD:
            return True
    # Fallback to query param ?key= for simple linkable downloads
    key = request.query_params.get("key")
    if key == settings.API_PASSWORD:
        return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
