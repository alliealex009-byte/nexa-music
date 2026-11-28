"""Search and link resolution: YouTube Data API -> yt-dlp search -> JioSaavn."""
import asyncio
import re

import yt_dlp

import config
from services import link_resolver, saavn, youtube_api, ytdlp_util
from services.models import Track
from utils.text import fmt_duration  # noqa: F401  (re-exported for handlers)

URL_RE = re.compile(r"^https?://\S+$", re.I)
YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def _entry_to_track(e: dict) -> Track | None:
    vid = e.get("id")
    if not vid:
        return None
    url = e.get("url") or e.get("webpage_url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    return Track(
        title=e.get("title") or "Unknown",
        url=url,
        duration=int(e.get("duration") or 0),
        thumbnail=(e.get("thumbnails") or [{}])[-1].get("url", "") or e.get("thumbnail", ""),
    )


def _ytsearch_work(query: str, limit: int):
    def work(opts):
        o = {**opts, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(o) as ydl:
            return ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    return work


async def search(query: str, limit: int = 5) -> list[Track]:
    """Best-effort search; never raises."""
    try:
        api = await asyncio.wait_for(youtube_api.search(query, limit), 8)
    except Exception:
        api = None
    if api:
        return api
    try:
        info, _ = await asyncio.wait_for(ytdlp_util.run(_ytsearch_work(query, limit)), 20)
        tracks = [t for t in (_entry_to_track(e) for e in (info.get("entries") or [])) if t]
        if tracks:
            return tracks
    except Exception:
        pass
    if config.SAAVN_FALLBACK:
        return await saavn.search(query, limit)
    return []


def _url_work(url: str, flat: bool):
    def work(opts):
        o = {**opts, "skip_download": True, "noplaylist": not flat, "extract_flat": "in_playlist" if flat else False}
        if flat:
            o["playlistend"] = config.MAX_PLAYLIST_IMPORT
        with yt_dlp.YoutubeDL(o) as ydl:
            return ydl.extract_info(url, download=False)
    return work


def _single_youtube_id(url: str) -> str | None:
    if _is_collection_url(url):
        return None
    host = link_resolver.host_of(url)
    if host not in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
        return None
    m = YT_ID_RE.search(url)
    return m.group(1) if m else None


def _is_collection_url(url: str) -> bool:
    return bool(re.search(r"[?&]list=|/playlist|/sets/|/album/", url)) and "watch?v=" not in url.split("list=")[0]


async def _from_url(url: str, limit: int) -> list[Track]:
    plat = link_resolver.platform(url)
    if plat == "saavn":
        one = await saavn.from_link(url)
        return [one] if one else []
    if plat:  # metadata-only platforms -> lazy search tracks
        queries = await link_resolver.to_queries(url, limit)
        return [Track(title=q, url=f"search:{q}", source="query") for q in queries]
    vid = _single_youtube_id(url)
    if vid:  # one video: read its details through the API / oEmbed so a blocked yt-dlp can't hide it
        track = (await youtube_api.video(vid)) or (await youtube_api.oembed(vid))
        if track:
            return [track]
        try:
            info, _ = await ytdlp_util.run(_url_work(url, flat=False))
            if info:
                return [Track(title=info.get("title") or "Unknown", url=info.get("webpage_url") or url,
                              duration=int(info.get("duration") or 0), thumbnail=info.get("thumbnail", ""))]
        except Exception:
            pass
        # still playable: the stream step reports the real reason if YouTube refuses it
        return [Track(title="YouTube video", url=f"https://www.youtube.com/watch?v={vid}")]
    try:
        info, _ = await ytdlp_util.run(_url_work(url, flat=_is_collection_url(url)))
    except Exception:
        return []
    if not info:
        return []
    if info.get("entries"):
        tracks = [t for t in (_entry_to_track(e) for e in info["entries"] if e) if t]
        return tracks[:limit]
    return [Track(
        title=info.get("title") or "Unknown",
        url=info.get("webpage_url") or url,
        duration=int(info.get("duration") or 0),
        thumbnail=info.get("thumbnail", ""),
    )]


async def resolve_many(query: str, limit: int = 1) -> list[Track]:
    """Text or link -> tracks. Collections (playlists/albums) return up to `limit` tracks."""
    query = query.strip()
    if URL_RE.match(query):
        return await _from_url(query, max(limit, 1))
    found = await search(query, 1)
    return found[:1]


async def resolve(query: str) -> Track | None:
    tracks = await resolve_many(query, 1)
    return tracks[0] if tracks else None


async def materialize(track: Track) -> Track | None:
    """Turn a lazy 'search:' track into a playable one (keeps requester info)."""
    if track.source != "query":
        return track
    query = track.url.removeprefix("search:")
    found = await search(query, 1)
    if not found:
        return None
    real = found[0]
    real.requested_by, real.requested_name, real.video = track.requested_by, track.requested_name, track.video
    if " - " in track.title:  # keep the nicer "Artist - Title" from the source platform
        real.title = track.title
    return real


def youtube_id(url: str) -> str | None:
    m = YT_ID_RE.search(url or "")
    return m.group(1) if m else None


async def related(track: Track, limit: int) -> list[Track]:
    """Tracks similar to `track` (YouTube radio mix, else a text search)."""
    vid = youtube_id(track.url)
    if vid:
        try:
            info, _ = await ytdlp_util.run(_url_work(f"https://www.youtube.com/watch?v={vid}&list=RD{vid}", flat=True))
            tracks = [t for t in (_entry_to_track(e) for e in (info or {}).get("entries") or [] if e) if t]
            tracks = [t for t in tracks if youtube_id(t.url) != vid]
            if tracks:
                return tracks[:limit]
        except Exception:
            pass
    base = re.sub(r"\(.*?\)|\[.*?\]", "", track.title).strip()
    found = await search(f"{base} similar songs", limit + 1)
    return [t for t in found if t.url != track.url][:limit]
