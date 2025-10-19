# TG Cloud Storage (Telegram + FastAPI)

A minimal personal "cloud" that stores files in Telegram via a bot and exposes a small FastAPI backend with a static HTML frontend.

Features
- Upload up to 2GB per file (Telegram Bot API limit)
- Streams uploads directly to Telegram without buffering the whole file
- Stores metadata (file_id, name, size) in SQLite by default or Postgres (e.g. Supabase) via `DATABASE_URL`
- List and search files by name
- Download streams from Telegram CDN through the backend
- Protects all API routes with a password via `X-API-KEY` or `Authorization: Bearer`

## Setup

Environment variables:
- `TELEGRAM_BOT_TOKEN` (required)
- `API_PASSWORD` (required)
- `DATABASE_URL` (optional) e.g. `postgresql://USER:PASSWORD@HOST:PORT/DB` (Supabase gives a URL)
- `BASE_URL` (optional) for CORS origin
- `TG_CHAT_ID` (required) target channel/group ID to store files

## Local development

Use your global/user Python. The examples below are for Windows PowerShell.

```powershell
# Install dependencies (user site if needed)
pip install -r backend\requirements.txt

# Set required environment variables
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:API_PASSWORD="your-strong-password"
$env:TG_CHAT_ID="-1001234567890"  # your private channel/group ID

# Optional
# $env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DB"
# $env:BASE_URL="http://localhost:8000"

# Run the API
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```
## Local development (no venv)

Use your global/user Python. The examples below are for Windows PowerShell.

```powershell
# Install dependencies (user site if needed)
pip install -r backend\requirements.txt

# Set required environment variables
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:API_PASSWORD="your-strong-password"
$env:TG_CHAT_ID="-1001234567890"  # your private channel/group ID

# Optional
# $env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DB"
# $env:BASE_URL="http://localhost:8000"

# Run the API
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `frontend/public/index.html` with Live Server or serve with any static server pointing to `frontend/public`. For quick test you can also just open it directly; set `window.API_BASE` in the devtools console if the backend runs on a different origin.

## Telegram chat target

Bots cannot send files to themselves as users. You need a destination chat to store documents:
- Create a private channel named e.g. "My TG Cloud".
- Add your bot as an Administrator.
- Get the channel ID (a negative ID) via forwarding a message to `@userinfobot` or using Telegram API tools.
- Set env var `TG_CHAT_ID` to that channel ID.

## Deploy

### Render (backend)
- Create a new Web Service from this repo
- Runtime: Python
- Build: `pip install -r backend/requirements.txt`
- Start: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- Env Vars: `TELEGRAM_BOT_TOKEN`, `API_PASSWORD`, `DATABASE_URL` (optional), `TG_CHAT_ID`

### Vercel (frontend)
- Framework preset: Other
- Root directory: `frontend`
- Output directory: `frontend/public`
- No build step needed (static)
- Set `NEXT_PUBLIC_API_BASE` or inject `window.API_BASE` with a simple `config.js` if needed.

## Notes
- Telegram `file_id` is stable but can change in rare cases; backend resolves a fresh CDN URL on every download via `getFile`.
- SQLite on Render uses ephemeral disk; for persistence, prefer Supabase Postgres via `DATABASE_URL`.
- File names are stored as provided by the browser; sanitize if exposing publicly.
- All API routes require a password via `X-API-KEY` header or `Authorization: Bearer`. The download route also accepts `?key=...` to simplify direct links from the frontend.
