"""Minimal raw Telegram Bot API client.

Used for messages that need newer Bot API features than the MTProto library knows about
(coloured buttons via `style`, premium-emoji icons via `icon_custom_emoji_id`).
"""
import logging

import aiohttp

import config

log = logging.getLogger("botapi")
_session: aiohttp.ClientSession | None = None


class BotApiError(Exception):
    def __init__(self, code: int, description: str):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    return _session


async def call(method: str, **params):
    url = f"{config.BOT_API_BASE}/bot{config.BOT_TOKEN}/{method}"
    async with _get_session().post(url, json=params) as r:
        try:
            data = await r.json(content_type=None)
        except Exception:
            raise BotApiError(r.status, "bad response")
    if not data.get("ok"):
        raise BotApiError(data.get("error_code", r.status), data.get("description", ""))
    return data["result"]


async def close():
    if _session and not _session.closed:
        await _session.close()
