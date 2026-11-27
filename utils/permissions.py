from pyrogram.enums import ChatMemberStatus, ChatType

import config
from database import auth as auth_db


def is_owner(user_id: int) -> bool:
    return user_id == config.OWNER_ID


def sender_id(message) -> int | None:
    return message.from_user.id if message.from_user else None


async def is_admin(client, chat_id: int, user_id: int) -> bool:
    if is_owner(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)


async def is_privileged(client, chat_id: int, user_id: int) -> bool:
    """Admin, bot owner, or someone authorized with /auth."""
    return await is_admin(client, chat_id, user_id) or await auth_db.is_authorized(chat_id, user_id)


async def message_is_admin(client, message) -> bool:
    """Like is_admin for a message; anonymous group admins (sent as the group) count as admins."""
    if message.chat.type == ChatType.PRIVATE:
        return False
    if message.from_user is None:
        return bool(message.sender_chat and message.sender_chat.id == message.chat.id)
    return await is_admin(client, message.chat.id, message.from_user.id)


async def message_is_privileged(client, message) -> bool:
    if message.from_user is None:
        return await message_is_admin(client, message)
    return await is_privileged(client, message.chat.id, message.from_user.id)


async def can_play(client, message, settings: dict) -> bool:
    mode = settings["play_mode"]
    if mode == "everyone":
        return True
    if mode == "admins":
        return await message_is_admin(client, message)
    return await message_is_privileged(client, message)


async def can_control(client, message, settings: dict) -> bool:
    """Playback controls: open to everyone unless administrator mode is on."""
    if message.chat.type == ChatType.PRIVATE:
        return False
    if not settings["admin_only"]:
        return True
    return await message_is_privileged(client, message)


async def can_play_uid(client, chat_id: int, user_id: int, settings: dict) -> bool:
    mode = settings["play_mode"]
    if mode == "everyone":
        return True
    if mode == "admins":
        return await is_admin(client, chat_id, user_id)
    return await is_privileged(client, chat_id, user_id)


async def can_control_uid(client, chat_id: int, user_id: int, settings: dict) -> bool:
    return (not settings["admin_only"]) or await is_privileged(client, chat_id, user_id)
