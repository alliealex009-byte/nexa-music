# AccStore Music Bot

Telegram voice-chat music bot (Pyrofork + py-tgcalls + yt-dlp + SQLite).

## Setup
1. Fill `.env` (API_ID, API_HASH, BOT_TOKEN, SESSION_STRING of the assistant account, OWNER_ID).
2. `docker compose up -d --build` (or `pip install -r requirements.txt && python app.py`; ffmpeg required).
3. Add the bot to a group as admin (delete messages + invite users), start a voice chat, `/play`.

## Owner setup in the bot's private chat
`/addkey` `/keys` `/rmkey` · `/addproxy` `/proxies` `/rmproxy` `/checkproxies` ·
`/setcookies` `/cookies` `/rmcookies` · `/setemoji` `/emojis` `/rmemoji` · `/grant` `/revoke` `/broadcast`
Secrets are never echoed back and your message is deleted after reading. Cookie text over 4096 characters
must be sent as a file. `data/nexa.db` stores these secrets (chmod 600): keep `data/` out of git and backups you share.

See `/help` in the bot for every command.
