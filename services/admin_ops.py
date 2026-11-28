"""Owner operations shared by the DM commands and the owner panel (all return HTML text)."""
import asyncio
import re
import shutil
import time
from datetime import datetime, timezone

import config
from database import credentials as cred
from database import groups as groups_db
from database import users as users_db
from services import (audio_provider, cookie_manager, player, proxy_manager, queue_manager, saavn, sysinfo, ui,
                      vc_monitor, youtube_api, ytdlp_util)
from utils.text import esc

KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")


def scrub(text: str) -> str:
    """Never echo secrets back, even inside error messages."""
    text = KEY_RE.sub("AIza…", text)
    return re.sub(r"((?:socks[45]h?|https?)://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


# ------------------------------------------------------------------ API keys
async def keys_overview() -> str:
    rows = await cred.list_keys()
    if not rows:
        return ("🔑 <b>YouTube API keys</b>\nNone added. Search uses yt-dlp instead (no quota).\n"
                "Get a key: Google Cloud Console → enable <i>YouTube Data API v3</i> → Credentials → API key.")
    now = datetime.now(timezone.utc).isoformat()
    lines = []
    for kid, key, until, invalid in rows:
        state = "❌ invalid" if invalid else (f"⏳ quota used, back {until[:16].replace('T', ' ')} UTC" if until and until > now else "✅ active")
        lines.append(f"#{kid} …{esc(key[-4:])} — {state}")
    return "🔑 <b>YouTube API keys</b>\n" + "\n".join(lines)


async def add_keys(text: str) -> list[str]:
    keys = KEY_RE.findall(text) or text.split()
    if not keys:
        return ["❌ I didn't find a key in that message."]
    lines = []
    for key in keys[:10]:
        ok, detail = await youtube_api.validate_key(key)
        if not ok:
            lines.append(f"❌ …{esc(key[-4:])} — {esc(scrub(detail))}")
            continue
        kid = await cred.add_key(key)
        lines.append(f"✅ #{kid} …{esc(key[-4:])} added ({esc(detail)})" if kid else f"ℹ️ …{esc(key[-4:])} already added")
    return lines


# ------------------------------------------------------------------ proxies
async def proxies_overview() -> str:
    rows = await cred.list_proxies()
    if not rows:
        return "🧦 <b>Proxies</b>\nNone added — downloads use the server's own connection."
    lines = []
    for pid, url, fails, ms, _ in rows:
        state = f"✅ {ms} ms" if fails == 0 and ms else f"⚠️ {fails} failed check(s)"
        lines.append(f"#{pid} <code>{esc(proxy_manager.mask(url))}</code> — {state}")
    return ("🧦 <b>Proxies</b>\n" + "\n".join(lines)
            + f"\n\nChecked every {config.PROXY_CHECK_INTERVAL}s; removed after {config.PROXY_MAX_FAILS} failed checks.")


async def add_proxies(text: str) -> list[str]:
    """Health-check every pasted proxy (20 at a time) and report a short summary, not one line per proxy."""
    raw = [l.strip() for l in re.split(r"[\n,]+", text) if l.strip() and not l.strip().startswith("#")]
    if not raw:
        return ["❌ I didn't find a proxy in that message."]
    raw = raw[:300]
    sem = asyncio.Semaphore(20)

    async def one(item):
        async with sem:
            try:
                return await proxy_manager.add(item)
            except proxy_manager.ProxyError as e:
                return "invalid", scrub(str(e))
            except Exception:
                return "dead", ""

    results = await asyncio.gather(*(one(i) for i in raw))
    count = {k: sum(1 for st, _ in results if st == k) for k in ("ok", "dead", "duplicate", "invalid")}
    lines = [f"✅ added: {count['ok']}   ❌ not reachable: {count['dead']}   ℹ️ duplicates: {count['duplicate']}"
             f"   ⚠️ unreadable: {count['invalid']}"]
    for st, masked in [r for r in results if r[0] == "ok"][:15]:
        lines.append(f"✅ <code>{esc(masked)}</code>")
    if count["ok"] > 15:
        lines.append(f"… and {count['ok'] - 15} more")
    if count["ok"] == 0 and count["dead"]:
        lines.append("\nℹ️ Free public proxies are usually dead or blocked by YouTube. A YouTube cookie (🍪) or a paid "
                     "residential SOCKS5 proxy works far better.")
    return lines


# ------------------------------------------------------------------ cookies
async def cookies_overview() -> str:
    rows = await cred.all_cookies()
    if not rows:
        return ("🍪 <b>Cookies</b>\nNone saved.\nYouTube cookies fix the \"Sign in to confirm you're not a bot\" block "
                "that VPS addresses often get.")
    lines = []
    for service, content, updated in rows:
        count, domains = cookie_manager.summarize(content)
        lines.append(f"• <b>{esc(service)}</b> — {count} cookies, {esc(', '.join(domains[:3]))} (updated {esc(updated[:10])})")
    return "🍪 <b>Cookies</b>\n" + "\n".join(lines)


async def verify_youtube_cookies(content: str | None = None) -> str:
    """Really try the stored YouTube cookies: can yt-dlp read a video's streams with them?"""
    content = content or await cred.get_cookies("youtube")
    if not content:
        return "🍪 No YouTube cookies saved yet."
    has_login, expired, total = cookie_manager.login_state(content)
    notes = []
    if not has_login:
        notes.append("⚠️ These cookies contain no Google login (SID / __Secure-3PSID). They were probably exported "
                     "while logged out.")
    if expired and expired >= total / 2:
        notes.append(f"⚠️ {expired} of {total} cookies are already expired. Export them again.")
    jar = cookie_manager.write_jar(content)

    def work():
        import yt_dlp

        o = {**ytdlp_util.base_opts(None, jar), "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(TEST_VIDEO, download=False)
            return len(info.get("formats") or []), bool(info.get("url") or any(f.get("acodec") != "none" for f in info.get("formats", [])))

    try:
        count, has_audio = await asyncio.wait_for(asyncio.to_thread(work), 90)
        if has_audio and count:
            verdict = f"✅ <b>YouTube cookies work</b> — {count} stream formats found."
        else:
            verdict = "⚠️ YouTube answered, but no audio streams came back (likely missing Deno / outdated yt-dlp)."
    except asyncio.TimeoutError:
        verdict = "⚠️ The test timed out (YouTube or the network is very slow)."
    except Exception as e:
        kind = audio_provider.classify(e)
        reason = {
            "blocked": "YouTube still says <i>sign in / not a bot</i> — the cookies are logged out, expired, or this "
                       "server's IP is flagged. Export fresh cookies from a <b>private window</b> logged in to YouTube, "
                       "close the window, then upload again; add a proxy if it persists.",
            "js": "yt-dlp can't solve YouTube's JavaScript challenge. Deno is missing or yt-dlp is outdated — rebuild the image.",
            "unavailable": "YouTube says the test video is unavailable from this server.",
        }.get(kind, f"yt-dlp failed: {esc(scrub(str(e))[:160])}")
        verdict = f"❌ <b>Cookies did not help:</b> {reason}"
    finally:
        cookie_manager.cleanup(jar)
    return "\n".join([verdict] + notes)


async def verify_spotify_cookies(content: str | None = None) -> str:
    """Spotify cookies: is the sp_dc login cookie there, not expired, and does Spotify still see a logged-in user?"""
    import time as _t

    import aiohttp

    content = content or await cred.get_cookies("spotify")
    if not content:
        return "🍪 No Spotify cookies saved yet."
    sp_dc = None
    for line in content.splitlines():
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5] == "sp_dc":
            sp_dc = (parts[6].strip(), int(parts[4]) if parts[4].isdigit() else 0)
    if not sp_dc or not sp_dc[0]:
        return ("❌ <b>No <code>sp_dc</code> login cookie</b> in this file — it was exported while logged out. "
                "Log in at open.spotify.com, export cookies again, upload.")
    if sp_dc[1] and sp_dc[1] < _t.time():
        return "❌ <b>The sp_dc cookie has expired.</b> Log in again and export fresh cookies."
    left = f" (valid for another {int((sp_dc[1] - _t.time()) / 86400)} days)" if sp_dc[1] else ""
    header = cookie_manager.header_for(content)
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get("https://open.spotify.com/get_access_token?reason=transport&productType=web_player",
                                headers={"Cookie": header, "User-Agent": ua}) as r:
                status = r.status
                data = await r.json(content_type=None) if status == 200 else {}
    except Exception:
        return f"⚠️ <b>sp_dc cookie present{left}</b>, but Spotify could not be reached to confirm it."
    if status == 200 and data.get("isAnonymous") is False:
        return f"✅ <b>Spotify cookies work</b> — logged in{left}."
    if status == 200 and data.get("isAnonymous") is True:
        return "❌ <b>Spotify sees you as logged out</b> — the cookie is invalid or was revoked. Export fresh cookies."
    return (f"⚠️ <b>sp_dc cookie present{left}</b>, but Spotify's check endpoint answered {status}, so I can't confirm "
            "it online. The cookie is only used to read Spotify link pages (playlists/albums); if links resolve, it works.")


async def save_cookies(service: str, raw: str) -> str:
    """Normalise + store. Raises cookie_manager.CookieError with a user-safe message."""
    content = cookie_manager.normalize(raw, service)
    await cred.set_cookies(service, content)
    count, domains = cookie_manager.summarize(content)
    note = ""
    if service in ("spotify", "apple"):
        note = ("\nℹ️ Used only to read Spotify/Apple link pages — never sent to other sites. "
                "Songs themselves are always played from YouTube/JioSaavn.")
    out = f"✅ Saved <b>{esc(service)}</b> cookies: {count} cookies ({esc(', '.join(domains[:4]))}).{note}"
    if service == "youtube":
        out += "\n\n🔍 Testing them now…\n" + await verify_youtube_cookies(content)
    elif service == "spotify":
        out += "\n\n🔍 Testing them now…\n" + await verify_spotify_cookies(content)
    return out


# ------------------------------------------------------------------ premium emoji
def emoji_overview() -> str:
    ids = ui.emoji_ids()
    if not ids:
        return ("✨ <b>Premium emoji</b>\nNone set. Pick a button name, then send one premium emoji.\n"
                "Needs the bot owner to have Telegram Premium (or a Fragment username on the bot).")
    return "✨ <b>Premium emoji</b>\n" + "\n".join(f"• {k}: {ui.em(k, '▫️')} <code>{v}</code>" for k, v in sorted(ids.items()))


# ------------------------------------------------------------------ stats / active calls / cache
async def stats_text() -> str:
    from database import users as users_db

    info = sysinfo.snapshot()
    keys = await cred.list_keys()
    usable = len(await cred.usable_keys())
    return "\n".join([
        "📊 <b>Stats</b>",
        f"👤 Users: {await users_db.count_users()}   👥 Groups: {await groups_db.count_groups()}",
        f"🎧 Active voice chats: {len(queue_manager.active_chats())}",
        f"🔑 API keys: {usable}/{len(keys)} usable   🧦 Proxies: {len(await cred.list_proxies())}   "
        f"🍪 Cookies: {len(await cred.all_cookies())}",
        "",
        f"🖥 CPU: {info['cpu'] if info['cpu'] is not None else 'n/a'}%   RAM: {info['ram']}",
        f"💾 Disk: {info['disk']}   ⏱ Uptime: {info['uptime']}",
        f"🐍 Python {info['python']} on {info['os']}",
    ])


async def av_text(client) -> str:
    chats = queue_manager.active_chats()
    if not chats:
        return "🎧 No active voice chats."
    lines = [f"🎧 <b>Active voice chats ({len(chats)})</b>"]
    for chat_id in chats[:30]:
        try:
            title = (await client.get_chat(chat_id)).title
        except Exception:
            title = str(chat_id)
        track = queue_manager.current(chat_id)
        state = "⏸ paused" if chat_id in player.manual_paused else "💤 auto-paused" if chat_id in player.auto_paused else "▶️"
        n = await vc_monitor.humans_in_call(chat_id)
        lines.append(f"• <b>{esc(title)}</b> <code>{chat_id}</code>\n  {state} {esc(track.title[:50]) if track else '—'} · 👥 {n if n is not None else '?'}")
    return "\n".join(lines)


async def clear_cache() -> str:
    removed = audio_provider.purge_cache(0, keep=player.sources_in_use())
    player._joined.clear()
    groups_db.invalidate()
    for chat_id in list(vc_monitor._empty_ticks):
        vc_monitor.forget(chat_id)
    return f"🧹 Cleared {removed} cached files and the assistant's join/settings caches."


# ------------------------------------------------------------------ diagnostics
TEST_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


async def diagnostics() -> str:
    lines = ["🔎 <b>Diagnostics</b>"]
    lines.append("✅ ffmpeg found" if shutil.which("ffmpeg") else "❌ ffmpeg missing (install it; the Docker image has it)")
    for helper in player.helpers():
        try:
            me = await player.assistant_info(helper)
            lines.append(f"✅ Helper #{helper.index}: @{esc(me.username or str(me.id))}")
        except Exception as e:
            lines.append(f"❌ Helper #{helper.index} not reachable ({esc(type(e).__name__)}) — check its session string")

    try:
        import yt_dlp.version as _v

        lines.append(f"ℹ️ yt-dlp {esc(_v.__version__)}")
    except Exception:
        pass
    runtime = ytdlp_util.js_runtime()
    lines.append(f"✅ JS runtime: {runtime}" if runtime else "❌ <b>No JS runtime (Deno)</b> — YouTube extraction will fail. "
                 "Rebuild the Docker image from the latest repo.")

    def work(opts):
        import yt_dlp

        with yt_dlp.YoutubeDL({**opts, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(TEST_VIDEO, download=False)
            if not any(f.get("acodec") not in (None, "none") for f in info.get("formats", [])):
                raise RuntimeError("no audio formats (challenge solving failed)")
            return info

    started = time.monotonic()
    try:
        await ytdlp_util.run(work)
        lines.append(f"✅ YouTube reachable ({time.monotonic() - started:.1f}s)")
    except Exception as e:
        kind = audio_provider.classify(e)
        if kind == "blocked":
            lines.append("❌ <b>YouTube is blocking this server</b> → add a YouTube cookie (then 🔍 Test) and/or a proxy")
        elif kind == "js":
            lines.append("❌ <b>yt-dlp can't solve YouTube's JS challenge</b> → Deno missing or yt-dlp outdated; rebuild the image")
        else:
            lines.append(f"❌ YouTube check failed: {esc(scrub(str(e))[:120])}")
    cookies = [c[0] for c in await cred.all_cookies()]
    lines.append(f"🍪 Cookies: {esc(', '.join(cookies)) if cookies else 'none'}")
    proxies = await cred.list_proxies()
    lines.append(f"🧦 Proxies: {len(proxies)} ({sum(1 for p in proxies if p[2] == 0)} healthy)")
    keys = await cred.list_keys()
    lines.append(f"🔑 API keys: {len(await cred.usable_keys())}/{len(keys)} usable" + ("" if keys else " (search uses yt-dlp)"))
    found = await saavn.search("arijit singh", 1)
    if found:
        lines.append(f"✅ JioSaavn working via <code>{esc(saavn._good or config.SAAVN_API_BASE)}</code>")
    else:
        lines.append("❌ <b>JioSaavn: no host answered.</b> Hosts tried: "
                     + ", ".join(f"<code>{esc(b)}</code>" for b in config.SAAVN_API_BASES)
                     + "\nSet <code>SAAVN_API_BASE</code> in .env to a working JioSaavn API (self-host one if public ones are down).")
    return "\n".join(lines)
