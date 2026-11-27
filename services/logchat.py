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


def target() -> int:
    return config.LOG_CHAT_ID or config.OWNER_ID


async def event(text: str):
    if not _enabled:
        return
    try:
        await ui.send(target(), text, sticky=True)
    except Exception:
        log.exception("log send")
