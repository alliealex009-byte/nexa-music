"""Watchdog: restarts the current track if the call dropped, keeping the queue."""
import asyncio
import inspect
import logging

from services import queue_manager

log = logging.getLogger("recovery")

CHECK_INTERVAL = 60
_missing: dict[int, int] = {}


async def _active_calls(calls) -> set[int]:
    c = calls.calls
    if inspect.isawaitable(c):
        c = await c
    if isinstance(c, dict):
        return set(c.keys())
    return {getattr(x, "chat_id", x) for x in c}


async def check_once(calls=None) -> list[int]:
    """Returns the chats that were restarted. `calls=None` checks every helper's call engine."""
    from services import player

    restarted = []
    try:
        engines = [calls] if calls is not None else [h.calls for h in player.helpers()]
        active: set[int] = set()
        for engine in engines:
            active |= await _active_calls(engine)
    except Exception:
        return restarted
    chats = set(queue_manager.active_chats())
    for gone in set(_missing) - chats:
        _missing.pop(gone, None)
    for chat_id in chats:
        if chat_id in active:
            _missing.pop(chat_id, None)
            continue
        _missing[chat_id] = _missing.get(chat_id, 0) + 1
        if _missing[chat_id] < 2:  # one grace round avoids racing a call that is still joining
            continue
        _missing.pop(chat_id, None)
        log.warning("call dropped in %s, restarting the current track", chat_id)
        if await player.restart_current(chat_id):
            restarted.append(chat_id)
        else:
            queue_manager.clear(chat_id)
    return restarted


async def _loop(calls=None):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            await check_once(calls)
        except Exception:
            log.exception("watchdog")


def start_watchdog(bot, calls=None):
    return asyncio.get_event_loop().create_task(_loop(calls))
