import html

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

import config
from database import groups as groups_db
from database import users as users_db
from keyboards.inline import help_hub, main_menu
from services import helptext, ui


def welcome_text(name: str, proxy_active: bool = False) -> str:
    name = html.escape(name)
    bot_name = html.escape(config.BOT_NAME)
    lines = [
        f"{ui.em('music', '⚡')} <b>ʜᴇʟʟᴏ {name}!</b>",
        "",
        f"<blockquote><b>🎵 {bot_name}</b>\nᴛʜᴇ ꜰᴀsᴛᴇsᴛ ᴡᴀʏ ᴛᴏ sᴛʀᴇᴀᴍ ᴍᴜsɪᴄ ɪɴ ᴛᴇʟᴇɢʀᴀᴍ ᴠᴏɪᴄᴇ ᴄʜᴀᴛs</blockquote>",
        "",
        "⚡ <b>Blazing-fast</b> audio &amp; video streaming",
        "💿 <b>YouTube · Spotify · Apple Music · SoundCloud · JioSaavn</b>",
        "🎤 Lyrics · ♾ Autoplay · 🔀 Mix · 🎧 Playlists",
        "🛡 Self-healing · pauses when the voice chat is empty",
    ]
    if proxy_active:
        lines.append("🟢 <b>Proxy bypass:</b> active")
    contacts = []
    if config.SUPPORT_GROUP:
        contacts.append(f"💬 Support: @{html.escape(config.SUPPORT_GROUP)}")
    if config.UPDATES_CHANNEL:
        contacts.append(f"📢 Updates: @{html.escape(config.UPDATES_CHANNEL)}")
    if contacts:
        lines += ["", "<blockquote expandable>" + "\n".join(contacts) + "</blockquote>"]
    lines += ["", "👇 <b>Tap a button below, or add me to a group and hit</b> /play"]
    return "\n".join(lines)


async def welcome_async(name: str) -> str:
    from database import credentials as cred

    return welcome_text(name, proxy_active=bool(await cred.list_proxies()))


async def send_welcome(message: Message, name: str):
    is_owner = bool(message.from_user and message.from_user.id == config.OWNER_ID)
    await ui.reply(message, await welcome_async(name), main_menu(ui.bot_username, is_owner),
                   photo=config.WELCOME_IMAGE or None, sticky=True)


async def show_home(q):
    """Back to the welcome screen (restoring the banner if the message was converted to plain text)."""
    text = await welcome_async(q.from_user.first_name)
    rows = main_menu(ui.bot_username, q.from_user.id == config.OWNER_ID)
    chat_id, mid = q.message.chat.id, q.message.id
    if config.WELCOME_IMAGE and not getattr(q.message, "photo", None):
        await ui.delete(chat_id, mid)
        await ui.send(chat_id, text, rows, photo=config.WELCOME_IMAGE, sticky=True)
    else:
        await ui.edit_cb(q, text, rows)


@Client.on_message(filters.command("id"))
async def id_cmd(client: Client, message: Message):
    uid = message.from_user.id if message.from_user else None
    lines = [f"🆔 <b>Your ID:</b> <code>{uid}</code>", f"💬 <b>Chat ID:</b> <code>{message.chat.id}</code>"]
    if uid == config.OWNER_ID:
        lines.append("👑 You are the bot owner — try /owner in a private chat.")
    await ui.reply(message, "\n".join(lines))


@Client.on_message(filters.command("start"))
async def start_cmd(client: Client, message: Message):
    user = message.from_user
    if not user:
        return
    if message.chat.type == ChatType.PRIVATE:
        await users_db.add_user(user.id, user.first_name)
    else:
        await groups_db.add_group(message.chat.id, message.chat.title or "")
    await send_welcome(message, user.first_name)


@Client.on_message(filters.command("help"))
async def help_cmd(client: Client, message: Message):
    await ui.reply(message, helptext.hub_text(), help_hub(), sticky=True)


@Client.on_message(filters.new_chat_members)
async def joined(client: Client, message: Message):
    me = await client.get_me()
    if any(u.id == me.id for u in message.new_chat_members):
        await groups_db.add_group(message.chat.id, message.chat.title or "")
        await ui.send(
            message.chat.id,
            "🎵 <b>Thanks for adding me!</b>\nMake me an admin (delete messages + invite users), start a "
            "voice chat and use /play. Settings: /settings · Help: /help",
            sticky=True,
        )
