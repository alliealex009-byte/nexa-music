"""Per-chat settings (cached for a few seconds; writes invalidate the cache)."""
import time

from database import connect

DEFAULTS = {
    "admin_only": True,  # "admin mode": playback controls limited to admins / authorized users
    "volume": 100,
    "auto_pause": True,  # pause when nobody is in the voice chat
    "idle_stop": True,  # leave the voice chat after it stayed empty for a while
    "play_mode": "everyone",  # who may start playback: everyone | admins | auth
    "delete_commands": False,  # delete users' command messages
    "auto_delete": 0,  # delete bot messages after N minutes (0 = off, 2-7)
    "silent": False,  # hide success messages
    "language": "en",
    "autoplay": False,
    "lyrics": False,  # show the Lyrics button and allow /lyrics in this group
    "karaoke": False,  # live lyric line on the now-playing card
}
BOOL_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, bool)}
CHOICES = {
    "play_mode": ("everyone", "admins", "auth"),
    "auto_delete": (0, 2, 3, 4, 5, 6, 7),
    "language": ("en", "hi"),
}
TTL = 15  # seconds
_cache: dict[int, tuple[float, dict]] = {}


def invalidate(chat_id: int | None = None):
    if chat_id is None:
        _cache.clear()
    else:
        _cache.pop(chat_id, None)


def _coerce(key: str, value):
    if value is None:
        return DEFAULTS[key]
    if key in BOOL_KEYS:
        return bool(value)
    if key in CHOICES:
        if key == "auto_delete":
            value = int(value)
        return value if value in CHOICES[key] else DEFAULTS[key]
    return value


async def add_group(chat_id: int, title: str):
    async with connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, ?)",
            (chat_id, title),
        )
        await db.commit()
    invalidate(chat_id)


async def get_settings(chat_id: int) -> dict:
    now = time.monotonic()
    hit = _cache.get(chat_id)
    if hit and now - hit[0] < TTL:
        return dict(hit[1])
    columns = ", ".join(DEFAULTS)  # fixed names from DEFAULTS, never user input
    async with connect() as db:
        cur = await db.execute(f"SELECT {columns} FROM groups WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
    if row:
        settings = {k: _coerce(k, v) for k, v in zip(DEFAULTS, row)}
    else:
        settings = dict(DEFAULTS)
    _cache[chat_id] = (now, settings)
    return dict(settings)


async def set_setting(chat_id: int, key: str, value):
    if key not in DEFAULTS:
        raise ValueError("invalid setting")
    if key in BOOL_KEYS:
        value = int(bool(value))
    elif key in CHOICES:
        if key == "auto_delete":
            value = int(value)
        if value not in CHOICES[key]:
            raise ValueError("invalid value")
    elif key == "volume":
        value = max(1, min(200, int(value)))
    async with connect() as db:
        await db.execute("INSERT OR IGNORE INTO groups (chat_id, title) VALUES (?, '')", (chat_id,))
        await db.execute(f"UPDATE groups SET {key} = ? WHERE chat_id = ?", (value, chat_id))
        await db.commit()
    invalidate(chat_id)


async def count_groups() -> int:
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM groups")
        return (await cur.fetchone())[0]
