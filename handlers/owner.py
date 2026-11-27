"""Owner-only management. Secrets (keys, cookies, proxy logins) are handled in private chat only."""
import asyncio
import logging
import os
import re
import tempfile

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

import config
from database import credentials as cred
from database import subscriptions as subs_db
from database import users as users_db
from services import cookie_manager, proxy_manager, ui, youtube_api
from utils.text import esc

log = logging.getLogger("owner")
owner_dm = filters.user(config.OWNER_ID) & filters.private
owner_any = filters.user(config.OWNER_ID)
KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")


def _scrub(text: str) -> str:
    """Never echo secrets back, even inside error messages."""
    text = KEY_RE.sub("AIza…", text)
    return re.sub(r"(socks5h?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


async def _forget(message: Message):
    """Remove the owner's message that contained a secret (best effort)."""
    try:
        await message.delete()
    except Exception:
        pass


def _args(message: Message) -> str:
    parts = (message.text or message.caption or "").split(None, 1)
    return parts[1] if len(parts) > 1 else ""


async def _read_document(client: Client, message: Message) -> str | None:
    """Text of an attached file (or of the file this message replies to)."""
    doc = message.document or (message.reply_to_message.document if message.reply_to_message else None)
    if not doc:
        return None
    if (doc.file_size or 0) > 512 * 1024:
        raise ValueError("That file is too large for a cookie file (max 512 KB).")
    holder = message if message.document else message.reply_to_message
    with tempfile.TemporaryDirectory() as tmp:
        path = await client.download_media(holder, file_name=os.path.join(tmp, "c.txt"))
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


# ------------------------------------------------------------------ YouTube API keys
@Client.on_message(filters.command("addkey") & owner_dm)
async def addkey_cmd(client, message):
    keys = KEY_RE.findall(_args(message)) or _args(message).split()
    await _forget(message)
    if not keys:
        return await ui.send(message.chat.id, "Usage: <code>/addkey KEY [KEY …]</code> (your message is deleted afterwards)")
    lines = []
    for key in keys[:10]:
        ok, detail = await youtube_api.validate_key(key)
        if not ok:
            lines.append(f"❌ …{esc(key[-4:])} — {esc(_scrub(detail))}")
            continue
        kid = await cred.add_key(key)
        lines.append(f"✅ #{kid} …{esc(key[-4:])} added ({esc(detail)})" if kid else f"ℹ️ …{esc(key[-4:])} already added")
    await ui.send(message.chat.id, "\n".join(lines), sticky=True)


@Client.on_message(filters.command("keys") & owner_dm)
async def keys_cmd(client, message):
    rows = await cred.list_keys()
    if not rows:
        return await ui.reply(message, "No API keys. Add one with /addkey. Without keys, search uses yt-dlp.")
    lines = []
    for kid, key, until, invalid in rows:
        state = "❌ invalid" if invalid else (f"⏳ quota used, back {until[:16].replace('T', ' ')} UTC" if until and until > _now() else "✅ active")
        lines.append(f"#{kid} …{esc(key[-4:])} — {state}")
    await ui.reply(message, "🔑 <b>YouTube API keys</b>\n" + "\n".join(lines))


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@Client.on_message(filters.command("rmkey") & owner_dm)
async def rmkey_cmd(client, message):
    arg = _args(message).strip().lower()
    if arg == "all":
        return await ui.reply(message, f"🗑 Removed {await cred.clear_keys()} keys.")
    if not arg.lstrip("#").isdigit():
        return await ui.reply(message, "Usage: <code>/rmkey id</code> or <code>/rmkey all</code> (see /keys)")
    ok = await cred.remove_key(int(arg.lstrip("#")))
    await ui.reply(message, "🗑 Removed." if ok else "❌ No key with that id.")


# ------------------------------------------------------------------ proxies
@Client.on_message(filters.command("addproxy") & owner_dm)
async def addproxy_cmd(client, message):
    raw = [l.strip() for l in re.split(r"[\n,]+", _args(message)) if l.strip()]
    await _forget(message)
    if not raw:
        return await ui.send(message.chat.id, "Usage: <code>/addproxy host:port</code> · <code>host:port:user:pass</code> · "
                                              "<code>socks5://user:pass@host:port</code> (one per line)")
    progress = await ui.send(message.chat.id, f"🔎 Checking {len(raw[:20])} prox{'y' if len(raw) == 1 else 'ies'}…")
    lines = []
    for item in raw[:20]:
        try:
            status, masked = await proxy_manager.add(item)
        except proxy_manager.ProxyError as e:
            lines.append(f"❌ {esc(_scrub(str(e)))}")
            continue
        icon = {"ok": "✅ added", "dead": "❌ not reachable (not added)", "duplicate": "ℹ️ already added"}[status]
        lines.append(f"{icon}: <code>{esc(masked)}</code>")
    text = "\n".join(lines)
    if progress:
        await ui.edit(message.chat.id, progress, text)
    else:
        await ui.send(message.chat.id, text)


@Client.on_message(filters.command("proxies") & owner_dm)
async def proxies_cmd(client, message):
    rows = await cred.list_proxies()
    if not rows:
        return await ui.reply(message, "No proxies. Downloads use a direct connection. Add with /addproxy.")
    lines = []
    for pid, url, fails, ms, checked in rows:
        state = f"✅ {ms} ms" if fails == 0 and ms else f"⚠️ {fails} failed check(s)"
        lines.append(f"#{pid} <code>{esc(proxy_manager.mask(url))}</code> — {state}")
    await ui.reply(message, "🧦 <b>SOCKS5 proxies</b>\n" + "\n".join(lines)
                   + f"\n\nChecked every {config.PROXY_CHECK_INTERVAL}s; removed after {config.PROXY_MAX_FAILS} failed checks.")


@Client.on_message(filters.command("rmproxy") & owner_dm)
async def rmproxy_cmd(client, message):
    arg = _args(message).strip().lower()
    if arg == "all":
        return await ui.reply(message, f"🗑 Removed {await cred.clear_proxies()} proxies.")
    if not arg.lstrip("#").isdigit():
        return await ui.reply(message, "Usage: <code>/rmproxy id</code> or <code>/rmproxy all</code> (see /proxies)")
    ok = await cred.remove_proxy(int(arg.lstrip("#")))
    await ui.reply(message, "🗑 Removed." if ok else "❌ No proxy with that id.")


@Client.on_message(filters.command("checkproxies") & owner_dm)
async def checkproxies_cmd(client, message):
    if not await cred.list_proxies():
        return await ui.reply(message, "No proxies to check.")
    progress = await ui.reply(message, "🔎 Checking all proxies…")
    alive, removed = await proxy_manager.check_all()
    text = f"✅ {alive} working · 🗑 {removed} removed"
    await (ui.edit(message.chat.id, progress, text) if progress else ui.reply(message, text))


# ------------------------------------------------------------------ cookies
@Client.on_message((filters.command("setcookies") | filters.command("addcookies")) & owner_dm)
async def setcookies_cmd(client, message):
    args = _args(message).split(None, 1)
    help_text = (
        "Usage: <code>/setcookies youtube</code> + a cookies.txt file (attach it, or reply to it with the command).\n"
        "Services: <code>youtube</code>, <code>spotify</code>, <code>apple</code>, or <code>other &lt;site&gt;</code>.\n"
        "Spotify also accepts just the <code>sp_dc</code> value: <code>/setcookies spotify sp_dc=…</code>.\n"
        "Cookie text over 4096 characters must be sent as a file."
    )
    if not args:
        return await ui.reply(message, help_text)
    try:
        if args[0].lower() == "other":
            rest = args[1].split(None, 1) if len(args) > 1 else []
            if not rest:
                return await ui.reply(message, help_text)
            service, inline = cookie_manager.resolve_service("other:" + rest[0]), (rest[1] if len(rest) > 1 else "")
        else:
            service, inline = cookie_manager.resolve_service(args[0]), (args[1] if len(args) > 1 else "")
        raw = await _read_document(client, message) or inline
        content = cookie_manager.normalize(raw, service)
    except (cookie_manager.CookieError, ValueError) as e:
        await _forget(message)
        return await ui.send(message.chat.id, f"❌ {esc(_scrub(str(e)))}")
    await cred.set_cookies(service, content)
    await _forget(message)
    count, domains = cookie_manager.summarize(content)
    note = ""
    if service == "spotify" or service == "apple":
        note = "\nℹ️ Used only to read Spotify/Apple link pages — never sent to other sites."
    await ui.send(message.chat.id, f"✅ Saved <b>{esc(service)}</b> cookies: {count} cookies "
                                   f"({esc(', '.join(domains[:4]))}).{note}\nYour message was deleted.", sticky=True)


@Client.on_message(filters.command("cookies") & owner_dm)
async def cookies_cmd(client, message):
    rows = await cred.all_cookies()
    if not rows:
        return await ui.reply(message, "No cookies saved. Use /setcookies.")
    lines = []
    for service, content, updated in rows:
        count, domains = cookie_manager.summarize(content)
        lines.append(f"• <b>{esc(service)}</b> — {count} cookies, {esc(', '.join(domains[:3]))} (updated {esc(updated[:10])})")
    await ui.reply(message, "🍪 <b>Cookies</b>\n" + "\n".join(lines))


@Client.on_message(filters.command("rmcookies") & owner_dm)
async def rmcookies_cmd(client, message):
    arg = _args(message).strip()
    if not arg:
        return await ui.reply(message, "Usage: <code>/rmcookies youtube</code> · <code>other &lt;site&gt;</code> · <code>all</code>")
    if arg.lower() == "all":
        return await ui.reply(message, f"🗑 Removed cookies for {await cred.clear_cookies()} services.")
    try:
        parts = arg.split()
        service = cookie_manager.resolve_service(f"other:{parts[1]}" if parts[0].lower() == "other" and len(parts) > 1 else parts[0])
    except cookie_manager.CookieError as e:
        return await ui.reply(message, f"❌ {esc(str(e))}")
    ok = await cred.remove_cookies(service)
    await ui.reply(message, f"🗑 Removed <b>{esc(service)}</b> cookies." if ok else "❌ No cookies saved for that service.")


# ------------------------------------------------------------------ premium emoji ids
@Client.on_message(filters.command("setemoji") & owner_dm)
async def setemoji_cmd(client, message):
    args = _args(message).split()
    if not args:
        return await ui.reply(message, "Usage: <code>/setemoji name</code> + one premium emoji, or "
                                       "<code>/setemoji name emoji_id</code>\nNames: " + ", ".join(ui.EMOJI_NAMES))
    name = args[0].lower()
    if name not in ui.EMOJI_NAMES:
        return await ui.reply(message, "Unknown name. Choose from: " + ", ".join(ui.EMOJI_NAMES))
    emoji_id = None
    for ent in message.entities or []:
        if ent.type == MessageEntityType.CUSTOM_EMOJI:
            emoji_id = str(ent.custom_emoji_id)
            break
    if not emoji_id and len(args) > 1 and args[1].isdigit():
        emoji_id = args[1]
    if not emoji_id:
        return await ui.reply(message, "Send a premium emoji in the message, or give its numeric id.")
    await cred.set_emoji(name, emoji_id)
    ui.set_emoji(name, emoji_id)
    await ui.reply(message, f"✅ <b>{name}</b> → {ui.em(name, '✨')}\n"
                            "Premium-emoji buttons need the bot owner to have Telegram Premium (or a Fragment "
                            "username on the bot). If Telegram refuses them, the bot falls back to normal buttons.")


@Client.on_message(filters.command("emojis") & owner_dm)
async def emojis_cmd(client, message):
    ids = ui.emoji_ids()
    if not ids:
        return await ui.reply(message, "No premium emoji set. Use /setemoji.")
    await ui.reply(message, "✨ <b>Premium emoji</b>\n" + "\n".join(f"• {k}: {ui.em(k, '▫️')} <code>{v}</code>" for k, v in sorted(ids.items())))


@Client.on_message(filters.command("rmemoji") & owner_dm)
async def rmemoji_cmd(client, message):
    arg = _args(message).strip().lower()
    if arg == "all":
        n = await cred.clear_emojis()
        await ui.load_emojis()
        return await ui.reply(message, f"🗑 Removed {n} emoji.")
    ok = await cred.remove_emoji(arg)
    ui.set_emoji(arg, None)
    await ui.reply(message, "🗑 Removed." if ok else "❌ Not set.")


# ------------------------------------------------------------------ premium + broadcast
@Client.on_message(filters.command("grant") & owner_any)
async def grant_cmd(client, message):
    try:
        uid, days = int(message.command[1]), int(message.command[2])
    except (IndexError, ValueError):
        return await ui.reply(message, "Usage: <code>/grant user_id days</code>")
    await subs_db.grant(uid, days)
    await ui.reply(message, f"✅ Granted {days} days to {uid}.")


@Client.on_message(filters.command("revoke") & owner_any)
async def revoke_cmd(client, message):
    try:
        uid = int(message.command[1])
    except (IndexError, ValueError):
        return await ui.reply(message, "Usage: <code>/revoke user_id</code>")
    await subs_db.revoke(uid)
    await ui.reply(message, "✅ Revoked.")


@Client.on_message(filters.command("broadcast") & owner_any)
async def broadcast_cmd(client, message):
    text = _args(message)
    if not text:
        return await ui.reply(message, "Usage: <code>/broadcast text</code>")
    sent = failed = 0
    for uid in await users_db.all_user_ids():
        try:
            await client.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await ui.reply(message, f"📣 Done. Sent: {sent}, failed: {failed}")
