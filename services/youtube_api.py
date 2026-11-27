"""YouTube Data API v3 search with key rotation (quota-aware)."""
import html
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

from database import credentials as cred
from services.models import Track

log = logging.getLogger("ytapi")
BASE = "https://www.googleapis.com/youtube/v3"
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
INVALID_REASONS = {"keyInvalid", "API_KEY_INVALID", "accessNotConfigured", "ipRefererBlocked", "forbidden"}


def next_reset() -> datetime:
    """Quota resets at midnight Pacific; 08:05 UTC is safely after that all year."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=8, minute=5, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def iso_seconds(value: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


class KeyProblem(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail)
        self.kind = kind  # quota | invalid | other


async def _get(path: str, params: dict, key: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(f"{BASE}/{path}", params={**params, "key": key}) as r:
            data = await r.json(content_type=None)
            if r.status == 200:
                return data
    err = (data or {}).get("error", {})
    reasons = {e.get("reason") for e in err.get("errors", [])}
    status = (err.get("status") or "").upper()
    if reasons & QUOTA_REASONS or status == "RESOURCE_EXHAUSTED":
        raise KeyProblem("quota", err.get("message", ""))
    if reasons & INVALID_REASONS or "API key not valid" in err.get("message", ""):
        raise KeyProblem("invalid", err.get("message", ""))
    raise KeyProblem("other", err.get("message", f"HTTP {r.status}"))


async def validate_key(key: str) -> tuple[bool, str]:
    """Cheap check (1 quota unit) used when the owner adds a key."""
    try:
        await _get("videos", {"part": "id", "id": "dQw4w9WgXcQ"}, key)
        return True, "ok"
    except KeyProblem as e:
        if e.kind == "quota":
            return True, "valid but today's quota is already used up"
        return False, str(e) or e.kind
    except Exception as e:
        return False, type(e).__name__


async def _search_with(key: str, query: str, limit: int) -> list[Track]:
    data = await _get(
        "search",
        {"part": "snippet", "q": query, "type": "video", "maxResults": limit, "videoCategoryId": "10"},
        key,
    )
    ids = [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:  # category 10 (Music) can be too narrow: retry without it
        data = await _get("search", {"part": "snippet", "q": query, "type": "video", "maxResults": limit}, key)
        ids = [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]
    if not ids:
        return []
    details = await _get("videos", {"part": "contentDetails,snippet", "id": ",".join(ids)}, key)
    tracks = []
    for v in details.get("items", []):
        sn = v["snippet"]
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
        tracks.append(
            Track(
                title=html.unescape(sn.get("title", "Unknown")),
                url=f"https://www.youtube.com/watch?v={v['id']}",
                duration=iso_seconds(v["contentDetails"].get("duration", "")),
                thumbnail=thumb,
            )
        )
    order = {i: n for n, i in enumerate(ids)}
    tracks.sort(key=lambda t: order.get(t.url.rsplit("=", 1)[-1], 99))
    return tracks


async def search(query: str, limit: int = 5) -> list[Track] | None:
    """Search via the API. Returns None when no key could serve the request (caller falls back)."""
    keys = await cred.usable_keys()
    for key_id, key in keys:
        try:
            return await _search_with(key, query, limit)
        except KeyProblem as e:
            if e.kind == "quota":
                await cred.mark_exhausted(key_id, next_reset())
                log.warning("YouTube API key #%s quota exhausted", key_id)
            elif e.kind == "invalid":
                await cred.mark_invalid(key_id)
                log.warning("YouTube API key #%s invalid", key_id)
            else:
                log.warning("YouTube API error (key #%s): %s", key_id, e)
                return None
        except Exception as e:
            log.warning("YouTube API request failed: %s", type(e).__name__)
            return None
    return None
