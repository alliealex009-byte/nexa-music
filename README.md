# RIA Music (Telegram VC music bot)

Pyrofork + py-tgcalls + yt-dlp + SQLite, runs in Docker. The bot name is `BOT_NAME` in `.env`.

## Setup
1. `cp .env .env.local` or just edit `.env` (use `nano .env`). Keep comments on their own lines.
2. Required: `API_ID`, `API_HASH`, `BOT_TOKEN`, `SESSION_STRING` (assistant account), `OWNER_ID`.
3. `docker compose up -d --build`, then `docker compose logs -f`.
4. Add the bot to a group as admin, start a voice chat, then `/play song`.

## Owner panel (your DM with the bot)
Send `/owner` (or tap **Owner Panel** on /start). Everything is a button:
API keys, Proxies (auto-removes dead ones), Cookies (YouTube / Spotify / Apple / other site),
Premium emoji, Premium users, Broadcast, Logger, Active VCs, Stats, Diagnostics.
Tap a button, then send the value as your next message (secrets are deleted from chat).

**Owner buttons doing nothing?** `OWNER_ID` is wrong. Send `/id` to the bot, put that number
in `.env` as `OWNER_ID=`, then `docker compose up -d --force-recreate`.

## YouTube blocked on a VPS
Datacenter IPs (Oracle, AWS...) are often blocked by YouTube ("Sign in to confirm you're not a bot").
Fix: Owner Panel -> Cookies -> YouTube (export cookies.txt from a throwaway Google account), and/or
Proxies -> add residential SOCKS5 proxies. The owner gets an alert when blocking is detected.

## JioSaavn fallback
Unofficial API hosts are listed in `SAAVN_API_BASE` (comma separated, tried in order). If all are down,
self-host a JioSaavn API and put its URL first. Test: `curl "https://saavn.sumit.co/api/search/songs?query=arijit"`.
Run Owner Panel -> Diagnostics (or `/diag`) to see what is failing.

## Assistant account
The assistant must be in the group. If it says a join request was sent, approve it in the group, or add the assistant manually.

## Banner
`assets/welcome.jpg` is the welcome image. Regenerate: `pip install pillow && python tools/make_banner.py "RIA MUSIC" assets/welcome.jpg`.
