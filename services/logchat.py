"""Optional log feed (/logger on): play events and errors are sent to the log chat."""
import logging

import config
from database import credentials as cred
from services import ui

log = logging.getLogger("logchat")
_enabled = False


async def load():
    global _enabled
    _enabled = (await cred.get_kv("logger", "0")) == "1"


def enabled() -> bool:
    return _enabled


async def set_enabled(value: bool):
    global _enabled
    _enabled = value
    await cred.set_kv("logger", "1" if value else "0")


_override = 0


def env_target() -> int:
    """LOG_CHAT_ID (or a common alias) from .env."""
    import os

    for name in ("LOG_CHAT_ID", "LOGGER_ID", "LOG_CHANNEL_ID", "LOG_CHANNEL", "LOGGER_CHAT_ID", "LOGGER_CHANNEL", "LOGGER"):
        raw = (os.getenv(name) or "").strip()
        if raw.lstrip("-").isdigit() and int(raw):
            return int(raw)
    return config.LOG_CHAT_ID


async def load_target():
    global _override
    raw = await cred.get_kv("logger_chat", "")
    _override = int(raw) if raw.lstrip("-").isdigit() else 0


async def set_target(chat_id: int):
    """0 = back to .env / owner DM."""
    global _override
    _override = chat_id
    await cred.set_kv("logger_chat", str(chat_id) if chat_id else "")


def target() -> int:
    return _override or env_target() or config.OWNER_ID


async def _send(text: str):
    """Straight to the Bot API so a failure is visible (ui.send hides errors and just returns None)."""
    from services import botapi

    await botapi.call("sendMessage", chat_id=target(), text=text, parse_mode="HTML",
                      link_preview_options={"is_disabled": True})


def explain(err: str) -> str:
    low = err.lower()
    if "chat not found" in low:
        return "chat not found — wrong ID, or this bot was never added to that channel"
    if "not enough rights" in low or "forbidden" in low or "administrator" in low:
        return "the bot is not an admin of that channel (or can't post). Add THIS bot as admin with “Post messages”"
    if "kicked" in low or "not a member" in low:
        return "the bot was removed from that channel — add it again as admin"
    return err


async def test() -> str | None:
    """Send a probe to the log chat. None = ok, otherwise the real reason it failed."""
    try:
        await _send("📝 <b>Logger connected.</b> Play events and errors will appear here.")
        return None
    except Exception as e:
        return explain(str(e)[:250])


_last_warn = 0.0


async def where(chat_id: int) -> str:
    """'Group name (-100123…)' for log lines."""
    from html import escape

    try:
        from database import groups as groups_db

        title = await groups_db.title_of(chat_id)
    except Exception:
        title = ""
    return f"<b>{escape(title)}</b> (<code>{chat_id}</code>)" if title else f"<code>{chat_id}</code>"


async def event(text: str):
    global _last_warn
    if not _enabled:
        return
    try:
        await _send(text)
    except Exception as e:
        import time

        reason = explain(str(e)[:250])
        log.warning("log send to %s failed: %s", target(), reason)
        if time.time() - _last_warn > 3600 and target() != config.OWNER_ID:
            _last_warn = time.time()
            try:
                await ui.send(config.OWNER_ID, f"⚠️ <b>Logger can't write to</b> <code>{target()}</code>\n{reason}\n"
                                               "Fix it, then run <code>/logger test</code>.")
            except Exception:
                pass
