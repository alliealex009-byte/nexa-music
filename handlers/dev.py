"""Developer commands (bot owner only)."""
import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatType

import config
from database import credentials as cred
from database import groups as groups_db
from database import users as users_db
from services import audio_provider, logchat, player, queue_manager, sysinfo, ui, vc_monitor
from utils.text import esc

log = logging.getLogger("dev")
owner_any = filters.user(config.OWNER_ID)


@Client.on_message(filters.command("ping") & owner_any)
async def ping_cmd(client, message):
    t0 = time.monotonic()
    mid = await ui.reply(message, "🏓 Pong…")
    ms = int((time.monotonic() - t0) * 1000)
    if mid:
        await ui.edit(message.chat.id, mid, f"🏓 Pong! <b>{ms} ms</b> · up {sysinfo.uptime()}")


@Client.on_message(filters.command("stats") & owner_any)
async def stats_cmd(client, message):
    info = sysinfo.snapshot()
    keys = await cred.list_keys()
    usable = len(await cred.usable_keys())
    proxies = await cred.list_proxies()
    cookies = [c[0] for c in await cred.all_cookies()]
    lines = [
        "📊 <b>Stats</b>",
        f"👤 Users: {await users_db.count_users()}   👥 Groups: {await groups_db.count_groups()}",
        f"🎧 Active voice chats: {len(queue_manager.active_chats())}",
        f"🔑 API keys: {usable}/{len(keys)} usable   🧦 Proxies: {len(proxies)}   🍪 Cookies: {len(cookies)}",
        "",
        f"🖥 CPU: {info['cpu'] if info['cpu'] is not None else 'n/a'}%   RAM: {info['ram']}",
        f"💾 Disk: {info['disk']}   ⏱ Uptime: {info['uptime']}",
        f"🐍 Python {info['python']} on {info['os']}",
    ]
    await ui.reply(message, "\n".join(lines))


@Client.on_message(filters.command(["av", "active"]) & owner_any)
async def av_cmd(client, message):
    chats = queue_manager.active_chats()
    if not chats:
        return await ui.reply(message, "No active voice chats.")
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
    await ui.reply(message, "\n".join(lines))


@Client.on_message(filters.command("clearass") & owner_any)
async def clearass_cmd(client, message):
    """Drop cached downloads and the assistant's in-memory state. Playing calls keep their files."""
    removed = audio_provider.purge_cache(0, keep=player.sources_in_use())
    player._joined.clear()
    groups_db.invalidate()
    for chat_id in list(vc_monitor._empty_ticks):
        vc_monitor.forget(chat_id)
    await ui.reply(message, f"🧹 Cleared {removed} cached files and the assistant's join/settings caches.")


@Client.on_message(filters.command("leaveall") & owner_any)
async def leaveall_cmd(client, message):
    if len(message.command) < 2 or message.command[1].lower() != "confirm":
        return await ui.reply(message, "⚠️ This makes the assistant leave <b>every</b> group/channel without an active "
                                       "call. Send <code>/leaveall confirm</code> to proceed.")
    progress = await ui.reply(message, "🚪 Leaving chats…")
    active = set(queue_manager.active_chats())
    left = failed = 0
    try:
        async for dialog in player._assistant.get_dialogs():
            chat = dialog.chat
            if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL) or chat.id in active:
                continue
            try:
                await player._assistant.leave_chat(chat.id)
                player._joined.discard(chat.id)
                left += 1
            except Exception:
                failed += 1
            await asyncio.sleep(1.2)  # stay under flood limits
    except Exception:
        log.exception("leaveall")
    text = f"✅ Left {left} chats ({failed} failed)."
    await (ui.edit(message.chat.id, progress, text) if progress else ui.reply(message, text))


@Client.on_message(filters.command("logger") & owner_any)
async def logger_cmd(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    if arg in ("on", "off"):
        await logchat.set_enabled(arg == "on")
    state = "on" if logchat.enabled() else "off"
    await ui.reply(message, f"📝 Logger is <b>{state}</b> → <code>{logchat.target()}</code>\n"
                            "Use <code>/logger on</code> or <code>/logger off</code>. Set LOG_CHAT_ID in .env to log elsewhere "
                            "(the bot must be able to write there).")
