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


async def test() -> str | None:
    """Send a probe to the log chat. None = ok, otherwise the reason it failed."""
    try:
        await ui.send(target(), "📝 <b>Logger connected.</b> Play events and errors will appear here.")
        return None
    except Exception as e:
        return str(e)[:200]


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
    if not _enabled:
        return
    try:
        await ui.send(target(), text, sticky=True)
    except Exception:
        log.exception("log send to %s failed (is the bot an admin there?)", target())
