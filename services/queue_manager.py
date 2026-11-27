import random
from collections import defaultdict, deque

import config
from services.models import Track

_queues: dict[int, deque[Track]] = defaultdict(deque)
_current: dict[int, Track] = {}
_loop: dict[int, str] = {}  # chat_id -> "track" | "queue" (absent = off)
_history: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=60))


def add(chat_id: int, track: Track) -> int | None:
    """Append. Returns position (1-based) or None if the queue is full."""
    q = _queues[chat_id]
    if len(q) >= config.MAX_QUEUE:
        return None
    q.append(track)
    return len(q)


def add_front(chat_id: int, track: Track):
    _queues[chat_id].appendleft(track)


def next_track(chat_id: int) -> Track | None:
    q = _queues[chat_id]
    if not q:
        _current.pop(chat_id, None)
        return None
    track = q.popleft()
    _current[chat_id] = track
    _history[chat_id].append(track.url)
    return track


def finish_current(chat_id: int, skipped: bool = False):
    """Apply loop mode to the track that just ended (call before next_track).

    A manual skip always moves on, even in single-track loop mode.
    """
    cur = _current.get(chat_id)
    mode = _loop.get(chat_id)
    if cur and mode == "track" and not skipped:
        add_front(chat_id, cur)
    elif cur and mode == "queue":
        _queues[chat_id].append(cur)


def current(chat_id: int) -> Track | None:
    return _current.get(chat_id)


def upcoming(chat_id: int) -> list[Track]:
    return list(_queues[chat_id])


def remove_at(chat_id: int, index: int) -> Track | None:
    q = _queues[chat_id]
    if not 1 <= index <= len(q):
        return None
    items = list(q)
    track = items.pop(index - 1)
    _queues[chat_id] = deque(items)
    return track


def clear_upcoming(chat_id: int) -> int:
    n = len(_queues[chat_id])
    _queues[chat_id].clear()
    return n


def shuffle(chat_id: int) -> int:
    items = list(_queues[chat_id])
    random.shuffle(items)
    _queues[chat_id] = deque(items)
    return len(items)


def clear(chat_id: int):
    _queues.pop(chat_id, None)
    _current.pop(chat_id, None)
    _loop.pop(chat_id, None)


def loop_mode(chat_id: int) -> str:
    return _loop.get(chat_id, "off")


def set_loop(chat_id: int, mode: str):
    if mode == "off":
        _loop.pop(chat_id, None)
    else:
        _loop[chat_id] = mode


def played_recently(chat_id: int) -> set[str]:
    return set(_history[chat_id])


def active_chats() -> list[int]:
    return list(_current)
