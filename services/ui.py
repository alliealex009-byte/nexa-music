"""Message sending/editing with coloured buttons and premium-emoji icons.

Every message goes through the raw Bot API first (so newer button fields work). If Telegram
rejects the fancy parts, it retries without icons, then without colours, then falls back to
the MTProto library with plain buttons. So the bot always answers, whatever the account can do.
"""
import asyncio
import logging
import os
import re

import config
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import credentials as cred
from database import groups as groups_db
from services import botapi
from utils.text import strip_html

log = logging.getLogger("ui")

_bot = None
bot_username = ""
_emoji: dict[str, str] = {}
_flags = {"icons": True, "style": True, "rich": True}
_tasks: set[asyncio.Task] = set()
_photo_ids: dict[str, str] = {}  # local banner path -> Telegram file_id (upload once)
CAPTION_LIMIT = 1024

# Names the owner can attach a premium emoji id to (/setemoji name id)
EMOJI_NAMES = [
    "play", "pause", "resume", "skip", "stop", "queue", "search", "playlist", "settings", "premium",
    "support", "updates", "help", "back", "close", "home", "lyrics", "loop", "shuffle", "mute",
    "autoplay", "video", "mix", "language", "silent", "admin", "delete", "add", "music", "check",
]
_TG_EMOJI_RE = re.compile(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", re.S)


def setup(bot, username: str = ""):
    global _bot, bot_username
    _bot, bot_username = bot, username


async def load_emojis():
    _emoji.clear()
    _emoji.update(dict(await cred.list_emojis()))


def set_emoji(name: str, emoji_id: str | None):
    if emoji_id:
        _emoji[name] = emoji_id
    else:
        _emoji.pop(name, None)
    _flags["icons"] = True  # owner changed something: try icons again


def emoji_ids() -> dict[str, str]:
    return dict(_emoji)


def em(name: str, fallback: str) -> str:
    """Inline premium emoji for message text (falls back to the normal emoji)."""
    eid = _emoji.get(name)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid and _flags["icons"] else fallback


def strip_emoji_tags(text: str) -> str:
    return _TG_EMOJI_RE.sub(r"\1", text)


def b(text: str, data: str | None = None, url: str | None = None, style: str | None = None,
      emoji: str | None = None) -> dict:
    """Button spec. style: primary | success | danger. emoji: a name from EMOJI_NAMES."""
    return {"text": text, "data": data, "url": url, "style": style, "emoji": emoji}


def _raw(rows, icons: bool, style: bool):
    out = []
    for row in rows:
        line = []
        for btn in row:
            d = {"text": btn["text"]}
            if btn.get("url"):
                d["url"] = btn["url"]
            else:
                d["callback_data"] = btn["data"] or "noop"
            if style and config.BUTTON_STYLES and btn.get("style"):
                d["style"] = btn["style"]
            if icons and btn.get("emoji") and _emoji.get(btn["emoji"]):
                d["icon_custom_emoji_id"] = _emoji[btn["emoji"]]
            line.append(d)
        out.append(line)
    return {"inline_keyboard": out}


def plain_markup(rows):
    if not rows:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(btn["text"], url=btn["url"]) if btn.get("url")
                else InlineKeyboardButton(btn["text"], callback_data=btn["data"] or "noop")
                for btn in row
            ]
            for row in rows
        ]
    )


_RETRYABLE = ("button", "style", "icon", "emoji", "reply markup", "entities", "parse", "can't parse")


async def _post(method: str, params: dict, rows, files: dict | None = None):
    levels = [(_flags["icons"], _flags["style"]), (False, _flags["style"]), (False, False)]
    seen, last = set(), None
    for icons, style in levels:
        if (icons, style) in seen:
            continue
        seen.add((icons, style))
        p = dict(params)
        if rows:
            p["reply_markup"] = _raw(rows, icons, style)
        if not icons:
            for key in ("text", "caption"):
                if key in p:
                    p[key] = strip_emoji_tags(p[key])
        try:
            return await botapi.call(method, files=files, **p)
        except botapi.BotApiError as e:
            desc = e.description.lower()
            if e.code != 400 or not any(k in desc for k in _RETRYABLE):
                raise
            last = e
            if ("emoji" in desc or "icon" in desc) and _flags["icons"]:
                _flags["icons"] = False
                log.warning("Telegram rejected premium-emoji icons (%s); using plain buttons", e.description)
            elif "style" in desc and _flags["style"]:
                _flags["style"] = False
                log.warning("Telegram rejected button styles (%s); using default colours", e.description)
    raise last  # type: ignore[misc]


async def send(chat_id: int, text: str, rows=None, *, reply_to: int | None = None, photo: str | None = None,
               sticky: bool = False, photo_bytes: bytes | None = None) -> int | None:
    """Send a message. Returns its id (None if it could not be sent at all)."""
    params: dict = {"chat_id": chat_id, "parse_mode": "HTML"}
    files = None
    if (photo or photo_bytes) and len(strip_html(text)) > CAPTION_LIMIT:
        photo = photo_bytes = None  # too long for a caption: send as a plain message
    if photo_bytes:
        method = "sendPhoto"
        params.update(caption=text)
        files = {"photo": ("card.jpg", photo_bytes, "image/jpeg")}
        photo = None
    elif photo:
        method = "sendPhoto"
        params.update(caption=text)
        if os.path.exists(photo):  # local banner: upload once, reuse the file_id afterwards
            if photo in _photo_ids:
                params["photo"] = _photo_ids[photo]
            else:
                with open(photo, "rb") as f:
                    files = {"photo": (os.path.basename(photo), f.read(), "image/jpeg")}
        else:
            params["photo"] = photo
    else:
        method = "sendMessage"
        params.update(text=text, link_preview_options={"is_disabled": True})
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    try:
        res = await _post(method, params, rows, files)
        mid = res["message_id"]
        if files and photo and res.get("photo"):
            _photo_ids[photo] = res["photo"][-1]["file_id"]
    except Exception as e:
        log.warning("raw send failed (%s); using fallback", e)
        mid = await _fallback_send(chat_id, text, rows, reply_to, photo)
    if mid:
        await _schedule_delete(chat_id, mid, sticky)
    return mid


async def _fallback_send(chat_id, text, rows, reply_to, photo):
    if _bot is None:
        return None
    text = strip_emoji_tags(text)
    try:
        if photo:
            m = await _bot.send_photo(chat_id, photo, caption=text, parse_mode=ParseMode.HTML,
                                      reply_markup=plain_markup(rows), reply_to_message_id=reply_to)
        else:
            m = await _bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=plain_markup(rows),
                                        reply_to_message_id=reply_to, disable_web_page_preview=True)
        return m.id
    except Exception as e:
        log.warning("fallback send failed in %s: %s", chat_id, type(e).__name__)
        return None


async def reply(message, text: str, rows=None, **kw) -> int | None:
    return await send(message.chat.id, text, rows, reply_to=message.id, **kw)


async def edit(chat_id: int, message_id: int, text: str, rows=None, caption: bool = False):
    method = "editMessageCaption" if caption else "editMessageText"
    params: dict = {"chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML"}
    if caption:
        params["caption"] = text
    else:
        params.update(text=text, link_preview_options={"is_disabled": True})
    params_rows = rows if rows is not None else []
    try:
        await _post(method, params, params_rows)
    except botapi.BotApiError as e:
        if "not modified" in e.description.lower():
            return
        log.info("raw edit failed (%s); using fallback", e)
        await _fallback_edit(chat_id, message_id, text, rows, caption)
    except Exception as e:
        log.info("raw edit failed (%s); using fallback", e)
        await _fallback_edit(chat_id, message_id, text, rows, caption)


async def _fallback_edit(chat_id, message_id, text, rows, caption):
    if _bot is None:
        return
    text = strip_emoji_tags(text)
    try:
        if caption:
            await _bot.edit_message_caption(chat_id, message_id, text, parse_mode=ParseMode.HTML,
                                            reply_markup=plain_markup(rows))
        else:
            await _bot.edit_message_text(chat_id, message_id, text, parse_mode=ParseMode.HTML,
                                         reply_markup=plain_markup(rows), disable_web_page_preview=True)
    except Exception as e:
        log.info("fallback edit failed: %s", type(e).__name__)


async def edit_cb(q, text: str, rows=None):
    """Edit the message a callback button belongs to."""
    is_photo = bool(getattr(q.message, "photo", None))
    if is_photo and len(strip_html(text)) > CAPTION_LIMIT:
        # a photo caption can't hold this much text: replace the photo message with a text message
        await delete(q.message.chat.id, q.message.id)
        await send(q.message.chat.id, text, rows, sticky=True)
        return
    await edit(q.message.chat.id, q.message.id, text, rows, caption=is_photo)


async def edit_markup(chat_id: int, message_id: int, rows):
    try:
        await _post("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id}, rows)
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        if _bot is not None:
            try:
                await _bot.edit_message_reply_markup(chat_id, message_id, plain_markup(rows))
            except Exception:
                pass


async def delete(chat_id: int, message_id: int):
    try:
        await botapi.call("deleteMessage", chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def _schedule_delete(chat_id: int, message_id: int, sticky: bool):
    if chat_id >= 0 or sticky:
        return
    minutes = (await groups_db.get_settings(chat_id))["auto_delete"]
    if not minutes:
        return

    async def later():
        await asyncio.sleep(minutes * 60)
        await delete(chat_id, message_id)

    task = asyncio.get_event_loop().create_task(later())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ------------------------------------------------------------------ rich messages (Bot API 10.1+: headings, tables, collapsible sections)
def _rich_unsupported(e) -> bool:
    d = e.description.lower()
    return e.code in (400, 404, 405) and any(k in d for k in ("method", "not found", "unsupported", "rich", "unknown"))


async def send_rich(chat_id: int, html_body: str, rows, fallback_text: str, reply_to: int | None = None,
                    sticky: bool = True) -> int | None:
    """Send a rich message; on servers/clients that don't know them, send the classic text instead."""
    if _flags["rich"]:
        params: dict = {"chat_id": chat_id, "rich_message": {"html": html_body, "skip_entity_detection": True}}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            res = await _post("sendRichMessage", params, rows)
            mid = res["message_id"]
            await _schedule_delete(chat_id, mid, sticky)
            return mid
        except botapi.BotApiError as e:
            log.warning("rich message failed (%s); using plain text", e)
            if _rich_unsupported(e):
                _flags["rich"] = False
        except Exception as e:
            log.warning("rich message failed (%s); using plain text", e)
    return await send(chat_id, fallback_text, rows, reply_to=reply_to, sticky=sticky)


async def edit_cb_rich(q, html_body: str, fallback_text: str, rows=None):
    """Edit a callback's message into a rich message (a photo message is replaced by a new one)."""
    chat_id, mid = q.message.chat.id, q.message.id
    if getattr(q.message, "photo", None):
        await delete(chat_id, mid)
        await send_rich(chat_id, html_body, rows, fallback_text)
        return
    if _flags["rich"]:
        try:
            await _post("editMessageText", {"chat_id": chat_id, "message_id": mid,
                                            "rich_message": {"html": html_body, "skip_entity_detection": True}}, rows or [])
            return
        except botapi.BotApiError as e:
            if "not modified" in e.description.lower():
                return
            log.warning("rich edit failed (%s); using plain text", e)
            if _rich_unsupported(e):
                _flags["rich"] = False
        except Exception as e:
            log.warning("rich edit failed (%s); using plain text", e)
    await edit_cb(q, fallback_text, rows)
