import asyncio
import logging
import random

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus

import config
from services import ui
from utils.guards import group_cmd
from utils.permissions import message_is_admin
from utils.text import esc

log = logging.getLogger("tagall")
EMOJIS = ["😀", "😎", "🔥", "✨", "🎵", "🎧", "💫", "🌟", "🎶", "💎", "🚀", "🌈", "🍀", "🦋", "🌸", "⚡", "🎉", "💖", "🥳", "🤩"]
_running: dict[int, bool] = {}


def mention(user_id: int, emoji: str) -> str:
    return f'<a href="tg://user?id={user_id}">{emoji}</a>'


async def _send(chat_id: int, text: str) -> bool:
    for _ in range(2):
        if await ui.send(chat_id, text, sticky=True):
            return True
        await asyncio.sleep(5)  # flood wait / transient failure: one retry
    return False


@Client.on_message(filters.command(["tagall", "utag"]) & filters.group)
@group_cmd
async def tagall_cmd(client, message, ctx):
    chat_id = message.chat.id
    if not await message_is_admin(client, message):
        return await ui.reply(message, ctx.t("admins_only"))
    if _running.get(chat_id):
        return await ui.reply(message, "A tag run is already going. Use /stoptag to stop it.")
    text = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""

    _running[chat_id] = True
    sent = 0
    batch: list[str] = []
    header = f"📣 <b>{esc(text)}</b>\n\n" if text else "📣 <b>Attention everyone!</b>\n\n"
    try:
        async for member in client.get_chat_members(chat_id):
            if not _running.get(chat_id) or sent >= config.TAGALL_MAX:
                break
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            if member.status in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT):
                continue
            batch.append(mention(user.id, random.choice(EMOJIS)))
            sent += 1
            if len(batch) >= config.TAGALL_PER_MESSAGE:
                await _send(chat_id, header + " ".join(batch))
                header, batch = "", []
                await asyncio.sleep(config.TAGALL_DELAY)
        if batch and _running.get(chat_id):
            await _send(chat_id, header + " ".join(batch))
    except Exception:
        log.exception("tagall failed")
    finally:
        stopped = not _running.pop(chat_id, False)
    await ui.send(chat_id, f"✅ {'Stopped after' if stopped else 'Tagged'} {sent} members.", sticky=True)


@Client.on_message(filters.command(["stoptag", "stopall"]) & filters.group)
@group_cmd
async def stoptag_cmd(client, message, ctx):
    if not await message_is_admin(client, message):
        return await ui.reply(message, ctx.t("admins_only"))
    if _running.get(message.chat.id):
        _running[message.chat.id] = False
    else:
        await ui.reply(message, "Nothing to stop.")
