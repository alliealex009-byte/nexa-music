"""Developer commands (bot owner only)."""
import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatType

import config
from services import admin_ops as ops
from services import logchat, player, queue_manager, sysinfo, ui
from utils.guards import owner_cmd
from utils.text import esc

log = logging.getLogger("dev")


@Client.on_message(filters.command("stats"))
@owner_cmd
async def stats_cmd(client, message):
    await ui.reply(message, await ops.stats_text())


@Client.on_message(filters.command(["av", "active"]))
@owner_cmd
async def av_cmd(client, message):
    await ui.reply(message, await ops.av_text(client))


@Client.on_message(filters.command("clearass"))
@owner_cmd
async def clearass_cmd(client, message):
    """Drop cached downloads and the assistant's in-memory state. Playing calls keep their files."""
    await ui.reply(message, await ops.clear_cache())


@Client.on_message(filters.command(["diag", "diagnose"]))
@owner_cmd
async def diag_cmd(client, message):
    progress = await ui.reply(message, "🔎 Running checks… (up to 30 seconds)")
    text = await ops.diagnostics()
    await (ui.edit(message.chat.id, progress, text) if progress else ui.reply(message, text))


@Client.on_message(filters.command("leaveall"))
@owner_cmd
async def leaveall_cmd(client, message):
    if len(message.command) < 2 or message.command[1].lower() != "confirm":
        return await ui.reply(message, "⚠️ This makes the assistant leave <b>every</b> group/channel without an active "
                                       "call. Send <code>/leaveall confirm</code> to proceed.")
    progress = await ui.reply(message, "🚪 Leaving chats…")
    active = set(queue_manager.active_chats())
    left = failed = 0
    try:
        for helper in player.helpers():
            async for dialog in helper.client.get_dialogs():
                chat = dialog.chat
                if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL) or chat.id in active:
                    continue
                try:
                    await helper.client.leave_chat(chat.id)
                    player._joined.discard(chat.id)
                    player._assign.pop(chat.id, None)
                    left += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(1.2)  # stay under flood limits
    except Exception:
        log.exception("leaveall")
    text = f"✅ Left {left} chats ({failed} failed)."
    await (ui.edit(message.chat.id, progress, text) if progress else ui.reply(message, text))


@Client.on_message(filters.command("logger"))
@owner_cmd
async def logger_cmd(client, message):
    args = [a.lower() for a in message.command[1:]]
    arg = args[0] if args else ""
    note = ""
    if arg in ("on", "off"):
        await logchat.set_enabled(arg == "on")
    elif arg == "set" and len(args) > 1 and args[1].lstrip("-").isdigit():
        await logchat.set_target(int(args[1]))
        err = await logchat.test()
        note = "\n✅ Test message sent." if not err else f"\n❌ Couldn't write there: <code>{err}</code>\nMake the bot an admin with post rights."
        if not err:
            await logchat.set_enabled(True)
    elif arg == "reset":
        await logchat.set_target(0)
    elif arg == "test":
        err = await logchat.test()
        note = "\n✅ Test message sent." if not err else f"\n❌ Failed: <code>{err}</code>"
    state = "on" if logchat.enabled() else "off"
    await ui.reply(message, f"📝 Logger is <b>{state}</b> → <code>{logchat.target()}</code>{note}\n"
                            "<code>/logger on|off</code> · <code>/logger set -100123…</code> (channel id) · "
                            "<code>/logger test</code> · <code>/logger reset</code>\n"
                            "Or put <code>LOG_CHAT_ID=-100…</code> in .env. The bot must be an admin of the channel.")
