"""Join-request verification: when someone asks to join a group where the bot is an admin, the bot DMs them a
Verify button. Verification always runs. Whether a verified member is also approved automatically is a group
admin's choice (/settings → Auto-accept joins, off by default)."""
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, ChatJoinRequest

from database import groups as groups_db
from services import ui
from services.ui import b
from utils.text import esc

log = logging.getLogger("joinreq")

PENDING_TTL = 30 * 60
_pending: dict[tuple[int, int], float] = {}  # (chat_id, user_id) -> when the request came in


def _prune():
    now = time.time()
    for key in [k for k, t in _pending.items() if now - t > PENDING_TTL]:
        _pending.pop(key, None)


@Client.on_chat_join_request()
async def join_request(client: Client, req: ChatJoinRequest):
    user, chat = req.from_user, req.chat
    if user is None or user.is_bot:
        return
    _prune()
    _pending[(chat.id, user.id)] = time.time()
    text = (f"<blockquote>🛂 <b>ᴠᴇʀɪꜰʏ ʏᴏᴜʀ ᴊᴏɪɴ ʀᴇǫᴜᴇsᴛ</b></blockquote>\n"
            f"Hi <b>{esc(user.first_name or 'there')}</b>! You asked to join <b>{esc(chat.title or 'the group')}</b>.\n"
            "Tap the button below to confirm you're a real person.")
    rows = [[b("✅ Verify me", f"jv:{chat.id}", style="success")]]
    try:
        await ui.send(user.id, text, rows)
    except Exception as e:  # the user can't be messaged: nothing to verify with
        log.info("could not DM join-request verification to %s: %s", user.id, type(e).__name__)


@Client.on_callback_query(filters.regex(r"^jv:-?\d+$"))
async def verify_cb(client: Client, q: CallbackQuery):
    chat_id = int(q.data.split(":")[1])
    user = q.from_user
    _prune()
    if (chat_id, user.id) not in _pending:
        return await q.answer("This verification expired. Send the join request again.", show_alert=True)
    _pending.pop((chat_id, user.id), None)
    settings = await groups_db.get_settings(chat_id)
    if settings.get("join_accept"):
        try:
            await client.approve_chat_join_request(chat_id, user.id)
            note = "✅ <b>Verified — you're in!</b> Welcome to the group."
        except Exception as e:
            log.info("approve failed in %s: %s", chat_id, type(e).__name__)
            note = ("✅ <b>Verified.</b> I couldn't approve you automatically, so please wait for a group admin "
                    "to accept your request.")
    else:
        note = "✅ <b>Verified.</b> Now wait for a group admin to accept your join request."
    await ui.edit_cb(q, note, None)
    await q.answer("Verified")
