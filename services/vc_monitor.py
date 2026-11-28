"""Watches voice chats: pause when nobody listens, resume when someone joins, leave when idle."""
import asyncio
import logging
import time

import config
from database import groups as groups_db
from services import player, queue_manager

log = logging.getLogger("vcmon")

_empty_ticks: dict[int, int] = {}
_empty_since: dict[int, float] = {}
_mute_paused: set[int] = set()  # chats paused because the assistant was muted in the voice chat


async def assistant_muted(chat_id: int, parts=None) -> bool | None:
    """True if an admin muted the assistant in the voice chat (so nobody can hear the music). None = unknown."""
    try:
        parts = parts if parts is not None else await player.participants(chat_id)
        me = await player.assistant_id(chat_id)
    except Exception:
        return None
    for p in parts:
        if getattr(p, "user_id", None) == me:
            by_admin = bool(getattr(p, "muted_by_admin", False))
            self_muted = bool(getattr(p, "muted", False)) and chat_id not in player.muted and chat_id not in player.manual_paused \
                and chat_id not in player.auto_paused
            return by_admin or self_muted
    return False


def forget(chat_id: int):
    _mute_paused.discard(chat_id)
    _empty_ticks.pop(chat_id, None)
    _empty_since.pop(chat_id, None)


async def humans_in_call(chat_id: int) -> int | None:
    """Number of listeners other than the assistant, or None if it can't be read."""
    try:
        parts = await player.participants(chat_id)
    except Exception:
        return None
    me = await player.assistant_id(chat_id)
    return sum(1 for p in parts if getattr(p, "user_id", None) != me)


async def tick(now: float | None = None) -> list[tuple[int, str]]:
    """One pass over active calls. Returns the actions taken (for logging/tests)."""
    now = time.monotonic() if now is None else now
    actions: list[tuple[int, str]] = []
    active = set(queue_manager.active_chats())
    for gone in set(_empty_ticks) - active:
        forget(gone)
    for chat_id in active:
        settings = await groups_db.get_settings(chat_id)
        muted = await assistant_muted(chat_id)
        if muted and chat_id not in player.manual_paused:
            if chat_id not in _mute_paused and await player.auto_pause(chat_id):
                _mute_paused.add(chat_id)
                actions.append((chat_id, "mute_paused"))
                await player._notice(chat_id, "assistant_muted")
            continue
        if muted is False and chat_id in _mute_paused:
            _mute_paused.discard(chat_id)
            if await player.auto_resume(chat_id):
                actions.append((chat_id, "mute_resumed"))
                await player._notice(chat_id, "assistant_unmuted")
        count = await humans_in_call(chat_id)
        if count is None:
            continue
        if count > 0:
            _empty_ticks.pop(chat_id, None)
            _empty_since.pop(chat_id, None)
            if settings["auto_pause"] and await player.auto_resume(chat_id):
                actions.append((chat_id, "resumed"))
                await player._notice(chat_id, "auto_resumed")
            continue

        _empty_ticks[chat_id] = _empty_ticks.get(chat_id, 0) + 1
        _empty_since.setdefault(chat_id, now)
        if settings["auto_pause"] and _empty_ticks[chat_id] >= config.VC_EMPTY_CHECKS:
            if await player.auto_pause(chat_id):
                actions.append((chat_id, "paused"))
                await player._notice(chat_id, "auto_paused")
        if settings["idle_stop"] and now - _empty_since[chat_id] >= config.VC_IDLE_STOP_SECONDS:
            await player.stop(chat_id)
            forget(chat_id)
            actions.append((chat_id, "stopped"))
            await player._notice(chat_id, "idle_stopped")
    return actions


async def _loop():
    while True:
        await asyncio.sleep(config.VC_CHECK_INTERVAL)
        try:
            await tick()
        except Exception:
            log.exception("vc monitor")


def start():
    return asyncio.get_event_loop().create_task(_loop())
