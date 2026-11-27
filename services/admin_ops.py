"""Owner operations shared by the DM commands and the owner panel (all return HTML text)."""
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
    return re.sub(r"(socks5h?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


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
        return "🧦 <b>SOCKS5 proxies</b>\nNone added — downloads use the server's own connection."
    lines = []
    for pid, url, fails, ms, _ in rows:
        state = f"✅ {ms} ms" if fails == 0 and ms else f"⚠️ {fails} failed check(s)"
        lines.append(f"#{pid} <code>{esc(proxy_manager.mask(url))}</code> — {state}")
    return ("🧦 <b>SOCKS5 proxies</b>\n" + "\n".join(lines)
            + f"\n\nChecked every {config.PROXY_CHECK_INTERVAL}s; removed after {config.PROXY_MAX_FAILS} failed checks.")


async def add_proxies(text: str) -> list[str]:
    raw = [l.strip() for l in re.split(r"[\n,]+", text) if l.strip()]
    if not raw:
        return ["❌ I didn't find a proxy in that message."]
    lines = []
    for item in raw[:20]:
        try:
            status, masked = await proxy_manager.add(item)
        except proxy_manager.ProxyError as e:
            lines.append(f"❌ {esc(scrub(str(e)))}")
            continue
        icon = {"ok": "✅ added", "dead": "❌ not reachable (not added)", "duplicate": "ℹ️ already added"}[status]
        lines.append(f"{icon}: <code>{esc(masked)}</code>")
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


async def save_cookies(service: str, raw: str) -> str:
    """Normalise + store. Raises cookie_manager.CookieError with a user-safe message."""
    content = cookie_manager.normalize(raw, service)
    await cred.set_cookies(service, content)
    count, domains = cookie_manager.summarize(content)
    note = ""
    if service in ("spotify", "apple"):
        note = "\nℹ️ Used only to read Spotify/Apple link pages — never sent to other sites."
    return f"✅ Saved <b>{esc(service)}</b> cookies: {count} cookies ({esc(', '.join(domains[:4]))}).{note}"


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
TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IJRE"


async def diagnostics() -> str:
    lines = ["🔎 <b>Diagnostics</b>"]
    lines.append("✅ ffmpeg found" if shutil.which("ffmpeg") else "❌ ffmpeg missing (install it; the Docker image has it)")
    try:
        me = await player.assistant_info()
        lines.append(f"✅ Assistant: @{esc(me.username or str(me.id))}")
    except Exception as e:
        lines.append(f"❌ Assistant account not reachable ({esc(type(e).__name__)}) — check SESSION_STRING")

    def work(opts):
        import yt_dlp

        with yt_dlp.YoutubeDL({**opts, "skip_download": True, "noplaylist": True}) as ydl:
            return ydl.extract_info(TEST_VIDEO, download=False)

    started = time.monotonic()
    try:
        await ytdlp_util.run(work)
        lines.append(f"✅ YouTube reachable ({time.monotonic() - started:.1f}s)")
    except Exception as e:
        kind = audio_provider.classify(e)
        if kind == "blocked":
            lines.append("❌ <b>YouTube is blocking this server</b> → add a YouTube cookie and/or a proxy")
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
