from pyrogram import Client, filters

from database import auth as auth_db
from services import ui
from utils.guards import group_cmd
from utils.permissions import message_is_admin
from utils.text import esc


async def _target(client, message):
    """(user_id, name) from a reply or an id/@username argument; None if missing."""
    r = message.reply_to_message
    if r and r.from_user:
        return r.from_user.id, r.from_user.first_name
    if len(message.command) > 1:
        ref = message.command[1].lstrip("@")
        try:
            user = await client.get_users(int(ref) if ref.lstrip("-").isdigit() else ref)
            return user.id, user.first_name
        except Exception:
            return None
    return None


@Client.on_message(filters.command("auth") & filters.group)
@group_cmd
async def auth_cmd(client, message, ctx):
    if not await message_is_admin(client, message):
        return await ui.reply(message, ctx.t("admins_only"))
    target = await _target(client, message)
    if not target:
        return await ui.reply(message, ctx.t("reply_to_user"))
    added = await auth_db.add(message.chat.id, target[0])
    await ui.reply(message, f"🔑 {esc(target[1])} is now authorized." if added else "Already authorized.")


@Client.on_message(filters.command("unauth") & filters.group)
@group_cmd
async def unauth_cmd(client, message, ctx):
    if not await message_is_admin(client, message):
        return await ui.reply(message, ctx.t("admins_only"))
    target = await _target(client, message)
    if not target:
        return await ui.reply(message, ctx.t("reply_to_user"))
    removed = await auth_db.remove(message.chat.id, target[0])
    await ui.reply(message, f"🚫 {esc(target[1])} is no longer authorized." if removed else "They weren't authorized.")


@Client.on_message(filters.command("authlist") & filters.group)
@group_cmd
async def authlist_cmd(client, message, ctx):
    ids = await auth_db.list_for(message.chat.id)
    if not ids:
        return await ui.reply(message, "No authorized users. Add one with /auth.")
    lines = []
    for uid in ids:
        try:
            u = await client.get_users(uid)
            lines.append(f"• <a href=\"tg://user?id={uid}\">{esc(u.first_name)}</a> (<code>{uid}</code>)")
        except Exception:
            lines.append(f"• <code>{uid}</code>")
    await ui.reply(message, "🔑 <b>Authorized users</b>\n" + "\n".join(lines))
