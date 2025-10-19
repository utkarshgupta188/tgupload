import asyncio
import os
from getpass import getpass

async def main():
    print("This script will generate a TG_SESSION_STRING for Pyrogram (user mode).\n")
    try:
        from pyrogram import Client
    except Exception as e:
        print("Pyrogram not installed or import failed:", e)
        print("Please run: pip install pyrogram tgcrypto")
        return

    api_id = os.environ.get("TG_API_ID") or input("Enter TG_API_ID: ")
    api_hash = os.environ.get("TG_API_HASH") or getpass("Enter TG_API_HASH (input hidden): ")

    if not api_id or not api_hash:
        print("TG_API_ID and TG_API_HASH are required.")
        return

    # Pyrogram expects an int for api_id
    try:
        api_id_int = int(api_id)
    except ValueError:
        print("TG_API_ID must be an integer.")
        return

    print("\nA Telelgram login will open in your terminal. Use your phone number and the code sent by Telegram.")
    print("If you have 2FA, enter your password when prompted.\n")

    async with Client("user_session", api_id=api_id_int, api_hash=api_hash) as app:
        session_string = await app.export_session_string()
        print("\nYour TG_SESSION_STRING (keep it secret):\n")
        print(session_string)
        print("\nSet it in your environment as TG_SESSION_STRING.\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
