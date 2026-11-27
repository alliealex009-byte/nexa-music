"""JioSaavn via an unofficial API. Parsing is tolerant of the two common response styles."""
import html
import logging

import aiohttp

import config
from services.models import Track

log = logging.getLogger("saavn")
QUALITY_ORDER = ("320kbps", "160kbps", "96kbps", "48kbps", "12kbps")


def _s(v) -> str:
    return html.unescape(str(v or ""))


def _download_url(song: dict) -> str:
    links = song.get("downloadUrl") or song.get("download_url") or []
    if isinstance(links, str):
        return links
    best = {}
    for item in links:
        if isinstance(item, dict):
            q = item.get("quality") or item.get("bitrate") or ""
            best[str(q)] = item.get("url") or item.get("link") or ""
    for q in QUALITY_ORDER:
        if best.get(q):
            return best[q]
    return next((u for u in best.values() if u), "")


def _artist(song: dict) -> str:
    a = song.get("artists")
    if isinstance(a, dict):
        names = [x.get("name", "") for x in (a.get("primary") or a.get("all") or [])]
        return ", ".join(n for n in names if n)
    return _s(song.get("primary_artists") or song.get("singers") or song.get("artist"))


def _image(song: dict) -> str:
    img = song.get("image")
    if isinstance(img, list) and img:
        last = img[-1]
        return last.get("url", "") if isinstance(last, dict) else str(last)
    return str(img or "")


def to_track(song: dict) -> Track | None:
    sid = song.get("id")
    if not sid:
        return None
    artist = _artist(song)
    name = _s(song.get("name") or song.get("title") or song.get("song"))
    title = f"{artist} - {name}" if artist else name
    return Track(
        title=title or "Unknown",
        url=f"saavn:{sid}",
        duration=int(song.get("duration") or 0),
        thumbnail=_image(song),
        source="saavn",
        stream_url=_download_url(song),
    )


_good: str | None = None  # last host that answered


def _bases() -> list[str]:
    bases = list(config.SAAVN_API_BASES)
    if _good in bases:
        bases.remove(_good)
        bases.insert(0, _good)
    return bases


async def _get(path: str, params: dict):
    """Try every configured host in turn; raise the last error if none answers."""
    global _good
    last: Exception | None = None
    timeout = aiohttp.ClientTimeout(total=15)
    for base in _bases():
        try:
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(f"{base}{path}", params=params) as r:
                    r.raise_for_status()
                    data = await r.json(content_type=None)
            _good = base
            return data
        except Exception as e:
            last = e
            log.info("saavn host %s failed: %s", base, type(e).__name__)
    raise last or RuntimeError("no JioSaavn API host configured")


def _results(data) -> list[dict]:
    if isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, dict):
            for k in ("results", "songs"):
                if isinstance(inner.get(k), list):
                    return inner[k]
                if isinstance(inner.get(k), dict) and isinstance(inner[k].get("data"), list):
                    return inner[k]["data"]
        if isinstance(inner, list):
            return inner
    if isinstance(data, list):
        return data
    return []


async def search(query: str, limit: int = 5) -> list[Track]:
    try:
        if config.SAAVN_API_STYLE == "legacy":
            data = await _get("/result/", {"query": query, "lyrics": "false"})
        else:
            data = await _get("/search/songs", {"query": query, "limit": limit})
    except Exception as e:
        log.info("saavn search failed: %s", type(e).__name__)
        return []
    out = [t for t in (to_track(s) for s in _results(data)[:limit]) if t]
    return out


async def from_link(link: str) -> Track | None:
    try:
        if config.SAAVN_API_STYLE == "legacy":
            data = await _get("/song/", {"query": link, "lyrics": "false"})
            items = _results(data) or ([data] if isinstance(data, dict) else [])
        else:
            data = await _get("/songs", {"link": link})
            items = _results(data)
    except Exception as e:
        log.info("saavn link failed: %s", type(e).__name__)
        return None
    return to_track(items[0]) if items else None


async def stream_url(track_id: str) -> str:
    """Fresh direct URL for a song id (stored URLs expire)."""
    try:
        if config.SAAVN_API_STYLE == "legacy":
            data = await _get("/song/get/", {"id": track_id})
            items = _results(data) or ([data] if isinstance(data, dict) else [])
        else:
            data = await _get(f"/songs/{track_id}", {})
            items = _results(data)
        return _download_url(items[0]) if items else ""
    except Exception as e:
        log.info("saavn stream failed: %s", type(e).__name__)
        return ""
