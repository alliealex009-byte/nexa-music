from pyrogram import Client, filters
from pyrogram.types import Message

import config
from database import subscriptions as subs_db
from services import ui


async def premium_text(user_id: int) -> str:
    exp = await subs_db.expiry(user_id)
    if exp:
        return f"💎 <b>Premium active</b>\nExpires: {exp:%Y-%m-%d} UTC"
    return (
        "💎 <b>Premium</b>\n"
        f"• Up to {config.PREMIUM_PLAYLIST_LIMIT} playlists (free: {config.FREE_PLAYLIST_LIMIT})\n\n"
        f"To upgrade, contact the owner via @{config.SUPPORT_GROUP}."
    )


@Client.on_message(filters.command("premium"))
async def premium_cmd(client: Client, message: Message):
    await ui.reply(message, await premium_text(message.from_user.id))
