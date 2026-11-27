import html

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

import config
from database import groups as groups_db
from database import users as users_db
from keyboards.inline import help_hub, main_menu
from services import helptext, ui


def welcome_text(name: str) -> str:
    name = html.escape(name)
    bot_name = html.escape(config.BOT_NAME)
    line = "⎯" * 26
    return (
        f"{ui.em('music', '⚡')} <b>ʜᴇʟʟᴏ {name}!</b>\n\n"
        f"🎵 <b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ {bot_name}</b> 🎵\n"
        f"{line}\n"
        "🚀 <b>ᴛʜᴇ ᴍᴏsᴛ ᴀᴅᴠᴀɴᴄᴇᴅ & sᴇʟꜰ-ʜᴇᴀʟɪɴɢ ᴍᴜsɪᴄ ʙᴏᴛ!</b>\n\n"
        "💿 <b>sᴇʀᴠɪᴄᴇs:</b> YouTube | Spotify | Apple Music | SoundCloud | JioSaavn\n"
        "⚡ <b>ᴇɴᴊᴏʏ:</b> HD Playback | Video | Lyrics | Auto-recovery\n"
        "🟢 <b>ᴘʀᴏxʏ ʙʏᴘᴀss:</b> Active &amp; Cookie-free\n\n"
        f"💬 <b>Support Group:</b> @{config.SUPPORT_GROUP}\n"
        f"📢 <b>Updates Channel:</b> @{config.UPDATES_CHANNEL}\n"
        f"{line}\n"
        "👉 <b>ᴛᴀᴘ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ɴᴀᴠɪɢᴀᴛᴇ ᴀʟʟ ꜰᴇᴀᴛᴜʀᴇs!</b>"
    )


async def send_welcome(message: Message, name: str):
    await ui.reply(message, welcome_text(name), main_menu(ui.bot_username),
                   photo=config.WELCOME_IMAGE or None, sticky=True)


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
