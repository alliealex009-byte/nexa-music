# RIA Music (Telegram VC music bot)

Pyrofork + py-tgcalls + yt-dlp (+Deno) + SQLite (+MongoDB backup), runs in Docker. The bot name is `BOT_NAME` in `.env`.

## Setup
1. Edit `.env` (`nano .env`). Keep comments on their own lines.
2. Required: `API_ID`, `API_HASH`, `BOT_TOKEN`, `SESSION_STRING` (helper #1), `OWNER_ID`.
3. `docker compose up -d --build`, then `docker compose logs -f`.
4. Add the bot to a group as admin, start a voice chat, then `/play song`.

## What users see
- **Now-playing card**: song image, live progress bar (`1:23 ━━●──── 3:45`) that updates every few seconds,
  ⏪10s / ⏸ Pause / 10s⏩, Skip, Stop, Autoplay on/off, Queue, More (mute/loop/shuffle).
- **Lyrics** and **Karaoke mode** (live lyric line on the card) are **off by default**; group admins switch them on in `/settings`.
- `/ping` works for everyone. The `/` command menu is registered automatically.

## Owner panel (`/owner` in DM)
API keys · Proxies (socks5/socks4/http, paste whole lists) · Cookies (with a real 🔍 test) · Premium emoji · Premium users ·
Broadcast · **Helpers** (add up to 10 session strings) · **Backup** (MongoDB) · Diagnostics.

**Owner buttons doing nothing?** `OWNER_ID` is wrong. Send `/id` to the bot, put that number in `.env`, `docker compose up -d --force-recreate`.

## YouTube
- The **YouTube API key** only gives search + video details. The audio itself always comes from **yt-dlp**.
- yt-dlp needs a JavaScript runtime to solve YouTube's challenges. The Docker image installs **Deno** and `yt-dlp[default]`
  (EJS solver). Rebuild with `docker compose build --no-cache` after pulling. `/diag` shows the runtime.
- Datacenter IPs (Oracle, AWS...) are often blocked. Fix: Owner Panel → Cookies → YouTube (export `cookies.txt` from a
  **private window** logged in to YouTube, close the window, upload) and press **🔍 Test YouTube cookies**. Proxies help too.
- A browser-extension VPN only changes your browser's traffic, not the server's. A server needs a proxy (SOCKS5/HTTP) instead.

## Helpers (assistant accounts)
One helper can stream in many voice chats at once. Extra helpers (max 10) spread the groups and avoid flood limits.
Each is renamed `RIA Music 1, 2, ...`, gets the bio "Always ads-free music 🎵", old profile photos are removed and
`assets/dp.jpg` (640x640) is set. Add them in Owner Panel → Helpers (paste a Pyrogram session string) or `SESSION_STRINGS`.

## MongoDB backup
Set `MONGO_URL` (Atlas free M0; in Atlas → Network Access allow your VPS IP). SQLite stays the live database; a snapshot
(keys, proxies, cookies, helpers, settings, playlists, users) is stored in MongoDB every `BACKUP_INTERVAL_MINUTES`, and restored
automatically on a fresh server with no local data. Manual: Owner Panel → Backup, or `python -m services.mongo_backup backup|restore`.
The snapshot contains secrets: keep the Atlas user private.

## JioSaavn
Public hosts are listed in `SAAVN_API_BASE` (comma separated, tried in order). To self-host, run an open-source JioSaavn API
container next to the bot (compose service name e.g. `jiosaavn-api`) and put `http://jiosaavn-api:<port>/api` first.
Test from the bot container: `docker compose exec nexa-music python -c "import urllib.request as u;print(u.urlopen('http://jiosaavn-api:3000/api/search/songs?query=arijit').read()[:200])"`.

## Pictures
`assets/welcome.jpg` is the welcome banner, `assets/dp.jpg` the square profile picture (set the bot's own picture in @BotFather → /setuserpic).

## v6 – reliability + Stella-style cards
- Skip / pause / resume / end / play now work back-to-back: stray "stream ended" events after a track switch are ignored, track changes are serialised per chat, and failed pause/resume report an error instead of silently doing nothing.
- Direct YouTube stream URLs are checked first; an unreadable URL (silent call) is downloaded instead. The next track is pre-resolved while the current one plays, so Skip is fast.
- New cards: rendered player image, `ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ ...` / `sᴛᴀʀᴛɪɴɢ sᴛʀᴇᴀᴍ ...` status, progress-time button, queued card (Play Now / Skip / Close), ping card, optional welcome card (Settings → Welcome card).
- Owner command `/debug` lists the last playback errors.

## v7 – helper account safety
- Each helper account connects through its **own** proxy (panel: 🧦 Proxies → add, then 🤖 Helpers → add). The proxy is saved with the account and never changes. Proxies are no longer used for yt-dlp unless `YTDLP_USE_PROXY=true`.
- Add helpers from the bot DM: 📱 phone number (code + 2FA) or session string.
- No more automatic profile changes: nothing is renamed/deleted at startup or when a helper is added; old photos are never deleted. The "Set names/bio/photo" button does it slowly, one account at a time.
- Helpers log in one at a time with a pause between them.
- Search: API 8 s → yt-dlp 20 s → JioSaavn, so it can no longer hang.

## v8
- Fixed: py-tgcalls 3.x rejected `filters.stream_end` (log: "object stream_end can't be used in 'await' expression"), so end-of-track / autoplay / queue advance never fired. Updates are now registered without filters and sorted by type.
- If a group requires admin approval for new members and the bot has the "invite users" right, the bot approves the assistant's join request itself.
- The now-playing card can no longer fail silently: errors are logged and a plain card is sent as a fallback; `/debug` shows card errors.
