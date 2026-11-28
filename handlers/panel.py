"""Owner panel: every owner tool behind buttons. Secrets are collected by replying to a prompt."""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType

import config
from database import credentials as cred
from database import subscriptions as subs_db
from database import users as users_db
from keyboards import owner as kb
from services import admin_ops as ops
from services import cookie_manager, helpers, logchat, mongo_backup, player, proxy_manager, ui
from utils.guards import owner_cmd
from utils.text import esc

log = logging.getLogger("panel")

PENDING: dict[int, dict] = {}       # owner id -> what the next message should be used for
_BROADCAST: dict[int, str] = {}     # owner id -> text waiting for confirmation

PROMPTS = {
    "addkey": "🔑 <b>Add API key</b>\nSend your YouTube Data API key (you can send several, one per line). "
              "I delete your message afterwards.",
    "addproxy": "🧦 <b>Add proxy</b>\nSend a proxy (socks5, socks4 or http):\n<code>host:port</code>\n<code>host:port:user:pass</code>\n"
                "<code>socks5://user:pass@host:port</code>\nOne per line for many; a trailing # 49ms is ignored. Each is health-checked before saving.",
    "cookie": "🍪 <b>Add {service} cookies</b>\nSend the <b>cookies.txt file</b> (Netscape format, or a JSON export). "
              "Text over 4096 characters must be a file. I delete your message afterwards.",
    "cookie_site": "🌐 <b>Other site</b>\nType the site name (for example <code>soundcloud</code>), then I'll ask for its cookies file.",
    "emoji": "✨ <b>Premium emoji for “{name}”</b>\nSend <b>one premium emoji</b> (or its numeric id).",
    "grant": "💎 <b>Grant premium</b>\nSend: <code>user_id days</code>  (example: <code>123456789 30</code>)",
    "revoke": "➖ <b>Revoke premium</b>\nSend the user id.",
    "addhelper": "🤖 <b>Add helper account</b>\nSend the <b>Pyrogram session string</b> of another Telegram account. "
                 "It connects through its own proxy (add proxies first). Names/bio/photo are only changed when you press the "
                 "Set names button. I delete your message afterwards.",
    "helperphone": "📱 <b>Add helper by phone</b>\nSend the account's phone number with country code "
                   "(e.g. <code>+1 555 123 4567</code>). The login goes through this account's own proxy.",
    "broadcast": "📣 <b>Broadcast</b>\nSend the message to send to every user who started the bot (plain text).",
}


# ------------------------------------------------------------------ rendering
async def render(page: str) -> tuple[str, list]:
    if page == "keys":
        return await ops.keys_overview(), kb.keys_menu(await cred.list_keys())
    if page == "proxies":
        return await ops.proxies_overview(), kb.proxies_menu(await cred.list_proxies())
    if page == "cookies":
        return await ops.cookies_overview(), kb.cookies_menu(await cred.all_cookies())
    if page == "emoji":
        return ops.emoji_overview(), kb.emoji_menu(ui.emoji_ids())
    if page == "helpers":
        return helpers.overview(), kb.helpers_menu(player.helpers(), len(player.helpers()) < config.MAX_HELPERS)
    if page == "backup":
        return mongo_backup.describe(), kb.backup_menu(mongo_backup.enabled())
    if page == "premium":
        return "💎 <b>Premium users</b>\nGrant or revoke premium (more playlists).", kb.premium_menu()
    return (
        f"🛠 <b>{esc(config.BOT_NAME)} — owner panel</b>\nEverything you can manage lives here. Pick a tool:",
        kb.home(logchat.enabled(), config.ENABLE_VPLAY),
    )


async def show(chat_id: int, page: str, notes: list[str] | None = None):
    text, rows = await render(page)
    if notes:
        text = "\n".join(notes) + "\n\n" + text
    await ui.send(chat_id, text, rows, sticky=True)


async def _prompt(q, action: str, **extra):
    PENDING[q.from_user.id] = {"action": action, **extra}
    await ui.edit_cb(q, PROMPTS.get(action, "Send the value.").format(**extra), kb.cancel_menu())


@Client.on_message(filters.command(["owner", "panel"]))
@owner_cmd(private_only=True)
async def owner_cmd_handler(client, message):
    PENDING.pop(message.from_user.id, None)
    text, rows = await render("home")
    await ui.reply(message, text, rows, sticky=True)


# ------------------------------------------------------------------ buttons
@Client.on_callback_query(filters.regex(r"^own:"))
async def own_cb(client, q):
    if q.from_user.id != config.OWNER_ID:
        return await q.answer("Owner only.", show_alert=True)
    parts = q.data.split(":")
    area = parts[1]
    act = parts[2] if len(parts) > 2 else ""
    arg = ":".join(parts[3:]) if len(parts) > 3 else ""
    uid = q.from_user.id

    async def page(name: str, note: str | None = None):
        text, rows = await render(name)
        await ui.edit_cb(q, (note + "\n\n" if note else "") + text, rows)

    if area == "home":
        PENDING.pop(uid, None)
        return await _answer(q, page("home"))
    if area in ("keys", "proxies", "cookies", "emoji", "premium", "helpers", "backup"):
        PENDING.pop(uid, None)
        return await _answer(q, page(area))
    if area == "cancel":
        PENDING.pop(uid, None)
        await helpers.login_cancel(uid)
        _BROADCAST.pop(uid, None)
        return await _answer(q, page("home"), "Cancelled")
    if area == "stats":
        await ui.edit_cb(q, await ops.stats_text(), [[kb.BACK]])
    elif area == "av":
        await ui.edit_cb(q, await ops.av_text(client), [[kb.BACK]])
    elif area == "clear":
        await ui.edit_cb(q, await ops.clear_cache(), [[kb.BACK]])
    elif area == "diag":
        await q.answer("Running checks…")
        await ui.edit_cb(q, "🔎 Running checks… (up to 30 seconds)", [[kb.BACK]])
        return await ui.edit_cb(q, await ops.diagnostics(), [[kb.BACK]])
    elif area == "vplay":
        config.ENABLE_VPLAY = not config.ENABLE_VPLAY
        await cred.set_kv("vplay_enabled", "1" if config.ENABLE_VPLAY else "0")
        return await _answer(q, page("home"), "Video play " + ("on" if config.ENABLE_VPLAY else "off"))
    elif area == "logger":
        await logchat.set_enabled(not logchat.enabled())
        return await _answer(q, page("home"), "Logger " + ("on" if logchat.enabled() else "off"))
    elif area == "k":
        if act == "add":
            return await _answer(q, _prompt(q, "addkey"))
        if act == "rm" and arg.isdigit():
            await cred.remove_key(int(arg))
        elif act == "all":
            await cred.clear_keys()
        return await _answer(q, page("keys"), "Removed")
    elif area == "p":
        if act == "add":
            return await _answer(q, _prompt(q, "addproxy"))
        if act == "check":
            await q.answer("Checking…")
            alive, removed = await proxy_manager.check_all() if await cred.list_proxies() else (0, 0)
            return await page("proxies", f"✅ {alive} working · 🗑 {removed} removed")
        if act == "rm" and arg.isdigit():
            await cred.remove_proxy(int(arg))
        elif act == "all":
            await cred.clear_proxies()
        return await _answer(q, page("proxies"), "Removed")
    elif area == "h":
        if act == "add":
            return await _answer(q, _prompt(q, "addhelper", bot=esc(config.BOT_NAME)))
        if act == "phone":
            return await _answer(q, _prompt(q, "helperphone"))
        if act == "brand":
            await q.answer("Updating profiles… (can take a minute)")
            report = await helpers.brand_all(force=True)
            return await page("helpers", "\n".join(esc(r) for r in report) or "Nothing to update.")
        if act == "rm" and arg.isdigit():
            return await page("helpers", await helpers.remove(int(arg)))
    elif area == "bk":
        if act == "now":
            await q.answer("Backing up…")
            return await page("backup", esc(await mongo_backup.backup_now(force=True)))
    elif area == "c":
        if act == "set" and arg == "ytnew":
            try:
                arg = cookie_manager.next_youtube_slot(await cookie_manager.youtube_services())
            except cookie_manager.CookieError as e:
                return await q.answer(str(e), show_alert=True)
            return await _answer(q, _prompt(q, "cookie", service=arg))
        if act == "set" and (arg in ("spotify", "apple") or cookie_manager.is_youtube(arg)):
            return await _answer(q, _prompt(q, "cookie", service=arg))
        if act == "other":
            return await _answer(q, _prompt(q, "cookie_site"))
        if act == "test" and arg == "spotify":
            await q.answer("Testing…")
            return await page("cookies", await ops.verify_spotify_cookies())
        if act == "test":
            await q.answer("Testing… (up to 90s)")
            await ui.edit_cb(q, "🔍 Testing every YouTube account against a real video…", [[kb.BACK]])
            return await page("cookies", await ops.verify_all_youtube())
        if act == "rm":
            await cred.remove_cookies(arg)
        elif act == "all":
            await cred.clear_cookies()
        return await _answer(q, page("cookies"), "Removed")
    elif area == "e":
        if act == "set" and arg in ui.EMOJI_NAMES:
            return await _answer(q, _prompt(q, "emoji", name=arg))
        if act == "all":
            await cred.clear_emojis()
            await ui.load_emojis()
        return await _answer(q, page("emoji"), "Cleared")
    elif area == "pr":
        return await _answer(q, _prompt(q, "grant" if act == "grant" else "revoke"))
    elif area == "bc":
        if act == "start":
            return await _answer(q, _prompt(q, "broadcast"))
        if act == "send":
            text = _BROADCAST.pop(uid, None)
            if not text:
                return await q.answer("Nothing to send.", show_alert=True)
            await q.answer("Sending…")
            sent, failed = await _broadcast(text)
            return await ui.edit_cb(q, f"📣 Done. Sent: {sent}, failed: {failed}", [[kb.BACK]])
    await q.answer()


async def _answer(q, coro, text: str | None = None):
    await coro
    await q.answer(text)


async def _broadcast(text: str) -> tuple[int, int]:
    sent = failed = 0
    for user_id in await users_db.all_user_ids():
        if await ui.send(user_id, esc(text), sticky=True):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)
    return sent, failed


# ------------------------------------------------------------------ the owner's next message
async def _forget(message):
    try:
        await message.delete()
    except Exception:
        pass


def _custom_emoji_id(message) -> str | None:
    for ent in (message.entities or []) + (getattr(message, "caption_entities", None) or []):
        if ent.type == MessageEntityType.CUSTOM_EMOJI:
            return str(ent.custom_emoji_id)
    return None


async def read_text_or_file(client, message) -> str | None:
    """Text of the message, or of an attached small text file."""
    doc = message.document
    if doc:
        if (doc.file_size or 0) > 512 * 1024:
            raise ValueError("That file is too large (max 512 KB).")
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = await client.download_media(message, file_name=os.path.join(tmp, "in.txt"))
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
    return message.text or message.caption


@Client.on_message(filters.private, group=5)
async def pending_input(client, message):
    uid = message.from_user.id if message.from_user else None
    if uid != config.OWNER_ID or uid not in PENDING:
        return
    text = (message.text or message.caption or "").strip()
    if text.startswith("/"):  # typing any command abandons the prompt
        PENDING.pop(uid, None)
        return
    state = PENDING.pop(uid)
    action, chat = state["action"], message.chat.id
    try:
        if action == "addkey":
            body = await read_text_or_file(client, message)
            await _forget(message)
            return await show(chat, "keys", await ops.add_keys(body or ""))
        if action == "addproxy":
            body = await read_text_or_file(client, message)
            await _forget(message)
            progress = await ui.send(chat, "🔎 Checking proxies…")
            lines = await ops.add_proxies(body or "")
            if progress:
                await ui.delete(chat, progress)
            return await show(chat, "proxies", lines)
        if action == "cookie_site":
            site = text.split()[0] if text else ""
            try:
                service = cookie_manager.resolve_service(f"other:{site}")
            except cookie_manager.CookieError as e:
                return await show(chat, "cookies", [f"❌ {esc(str(e))}"])
            PENDING[uid] = {"action": "cookie", "service": service}
            return await ui.send(chat, PROMPTS["cookie"].format(service=esc(service)), kb.cancel_menu())
        if action == "addhelper":
            session = (message.text or "").strip()
            await _forget(message)
            await ui.send(chat, "⏳ Logging the helper in…")
            result = await helpers.add_from_owner(session)
            return await show(chat, "helpers", [result])
        if action == "helperphone":
            await _forget(message)
            note = await ui.send(chat, "⏳ Asking Telegram for the login code…")
            result = await helpers.login_begin(uid, text)
            if note:
                await ui.delete(chat, note)
            if result != "OK":
                return await show(chat, "helpers", [result])
            PENDING[uid] = {"action": "helpercode"}
            return await ui.send(chat, "📨 A code was sent to that account in Telegram.\n<b>Type it with spaces or dashes</b> "
                                 "(e.g. <code>1 2 3 4 5</code>) — Telegram cancels the login if the code is sent as one plain number.",
                                 kb.cancel_menu())
        if action in ("helpercode", "helperpass"):
            await _forget(message)
            fn = helpers.login_code if action == "helpercode" else helpers.login_password
            result = await fn(uid, text)
            if result == "PASSWORD":
                PENDING[uid] = {"action": "helperpass"}
                return await ui.send(chat, "🔐 This account has two-step verification. Send its password "
                                     "(I delete your message).", kb.cancel_menu())
            if result.startswith("RETRY:"):
                PENDING[uid] = state
                return await ui.send(chat, result[6:], kb.cancel_menu())
            return await show(chat, "helpers", [result])
        if action == "cookie":
            service = state["service"]
            try:
                raw = await read_text_or_file(client, message)
                note = await ops.save_cookies(service, raw or "")
            except (cookie_manager.CookieError, ValueError) as e:
                await _forget(message)
                PENDING[uid] = state  # let them try again
                return await ui.send(chat, f"❌ {esc(ops.scrub(str(e)))}\nSend the file again, or cancel.", kb.cancel_menu())
            await _forget(message)
            return await show(chat, "cookies", [note, "Your message was deleted."])
        if action == "emoji":
            emoji_id = _custom_emoji_id(message) or (text if text.isdigit() else None)
            if not emoji_id:
                PENDING[uid] = state
                return await ui.send(chat, "That wasn't a premium emoji. Send one premium emoji (or its numeric id).", kb.cancel_menu())
            await cred.set_emoji(state["name"], emoji_id)
            ui.set_emoji(state["name"], emoji_id)
            return await show(chat, "emoji", [f"✅ <b>{esc(state['name'])}</b> → {ui.em(state['name'], '✨')}"])
        if action == "grant":
            parts = text.split()
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                PENDING[uid] = state
                return await ui.send(chat, "Send: <code>user_id days</code>", kb.cancel_menu())
            await subs_db.grant(int(parts[0]), int(parts[1]))
            return await show(chat, "premium", [f"✅ Granted {parts[1]} days to {parts[0]}."])
        if action == "revoke":
            if not text.isdigit():
                PENDING[uid] = state
                return await ui.send(chat, "Send the numeric user id.", kb.cancel_menu())
            await subs_db.revoke(int(text))
            return await show(chat, "premium", ["✅ Revoked."])
        if action == "broadcast":
            if not text:
                PENDING[uid] = state
                return await ui.send(chat, "Send the text to broadcast.", kb.cancel_menu())
            _BROADCAST[uid] = text
            count = len(await users_db.all_user_ids())
            return await ui.send(chat, f"📣 <b>Preview</b>\n\n{esc(text)}", kb.confirm_broadcast(count), sticky=True)
    except Exception:
        log.exception("panel input failed (%s)", action)
        await ui.send(chat, "⚠️ That failed — see the bot log.", kb.cancel_menu())
