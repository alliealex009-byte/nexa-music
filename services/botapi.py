"""Minimal raw Telegram Bot API client.

Used for messages that need newer Bot API features than the MTProto library knows about
(coloured buttons via `style`, premium-emoji icons via `icon_custom_emoji_id`).
"""
import json
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


async def call(method: str, files: dict | None = None, **params):
    """files: {field: (filename, bytes, content_type)} switches to a multipart upload."""
    url = f"{config.BOT_API_BASE}/bot{config.BOT_TOKEN}/{method}"
    if files:
        form = aiohttp.FormData()
        for key, value in params.items():
            form.add_field(key, value if isinstance(value, str) else json.dumps(value))
        for key, (name, data, ctype) in files.items():
            form.add_field(key, data, filename=name, content_type=ctype)
        request = _get_session().post(url, data=form)
    else:
        request = _get_session().post(url, json=params)
    async with request as r:
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
