from pyrogram import Client, filters

from database import groups as groups_db
from keyboards import settings as kb
from services import ui
from utils.guards import group_cmd
from utils.permissions import message_is_admin


@Client.on_message(filters.command("settings") & filters.group)
@group_cmd
async def settings_cmd(client, message, ctx):
    if not await message_is_admin(client, message):
        return await ui.reply(message, ctx.t("admins_only"))
    await groups_db.add_group(message.chat.id, message.chat.title or "")
    s = await groups_db.get_settings(message.chat.id)
    text, rows = kb.page("home", s)
    await ui.reply(message, text, rows, sticky=True)


@Client.on_message(filters.command("settings") & filters.private)
async def settings_private(client, message):
    await ui.reply(message, "Use /settings inside a group to change that group's settings.")
