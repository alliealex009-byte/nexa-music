"""Autoplay: when the queue runs out, queue songs related to the last one."""
from services import music_search, queue_manager
from services.models import Track

BATCH = 5


async def pick(chat_id: int, last: Track) -> list[Track]:
    seen = queue_manager.played_recently(chat_id) | {last.url}
    found = await music_search.related(last, BATCH * 3)
    fresh = [t for t in found if t.url not in seen][:BATCH]
    for t in fresh:
        t.requested_by, t.requested_name, t.video = 0, "Autoplay", last.video
    return fresh
