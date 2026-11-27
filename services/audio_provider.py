"""Turns a Track into something ffmpeg can read: a direct URL or a cached local file."""
import asyncio
import logging
import os
import re
import time

import yt_dlp

import config
from services import music_search, proxy_manager, saavn, ytdlp_util
from services.models import Track

log = logging.getLogger("audio")

# async fn(text) -> None, set by app.py: tells the owner YouTube is blocking this server
alert_hook = None
_last_alert = 0.0
ALERT_EVERY = 3600


def classify(exc: Exception) -> str:
    text = str(exc).lower()
    if "sign in to confirm" in text or "not a bot" in text or "http error 429" in text or "too many requests" in text:
        return "blocked"
    if any(k in text for k in ("video unavailable", "private video", "has been removed", "not available in your country",
                               "age-restricted", "members-only", "premieres in")):
        return "unavailable"
    return "failed"


async def _alert_blocked():
    global _last_alert
    now = time.time()
    if alert_hook is None or now - _last_alert < ALERT_EVERY:
        return
    _last_alert = now
    try:
        await alert_hook(
            "⚠️ <b>YouTube is blocking this server.</b>\n"
            "Songs can't be fetched until you add a YouTube <b>cookie</b> or a <b>proxy</b>.\n"
            "Open the owner panel → 🍪 Cookies / 🧦 Proxies. (JioSaavn keeps working as a fallback.)"
        )
    except Exception:
        log.exception("owner alert")


def _filter():
    return yt_dlp.utils.match_filter_func(f"!is_live & duration<?{config.MAX_DOWNLOAD_SECONDS}")


def _fmt(video: bool) -> str:
    if video:
        h = config.VIDEO_MAX_HEIGHT
        return f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
    return "bestaudio/best"


def _download_work(url: str, video: bool):
    def work(opts):
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        o = {**opts, "format": _fmt(video), "noplaylist": True,
             "outtmpl": os.path.join(config.CACHE_DIR, "%(id)s.%(ext)s"),
             "match_filter": _filter(), "continuedl": True}
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise RuntimeError("filtered")
            return ydl.prepare_filename(info)
    return work


def _extract_work(url: str, video: bool):
    def work(opts):
        o = {**opts, "format": _fmt(video), "noplaylist": True, "skip_download": True, "match_filter": _filter()}
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or not info.get("url"):
                raise RuntimeError("no stream url")
            return info["url"]
    return work


async def _youtube_source(track: Track) -> str | None:
    # stream URLs are locked to the IP that requested them, so with proxies in use the file is
    # downloaded through the proxy and played from disk. Without proxies, stream the URL directly.
    use_proxy = bool(await proxy_manager.pick())
    try:
        if use_proxy or track.video:
            path, _ = await ytdlp_util.run(_download_work(track.url, track.video))
            return path if os.path.exists(path) else None
        url, _ = await ytdlp_util.run(_extract_work(track.url, False), use_proxy=False)
        return url
    except Exception as e:
        track.error = classify(e)
        log.info("youtube source failed (%s): %s", track.error, str(e)[:160])
        if track.error == "blocked":
            await _alert_blocked()
        return None


def _clean_title(title: str) -> str:
    title = re.sub(r"\(.*?\)|\[.*?\]|\|.*$", "", title)
    title = re.sub(r"\b(official|video|audio|lyrics?|lyrical|hd|4k|full song)\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -")


async def _saavn_fallback(track: Track) -> str | None:
    if not config.SAAVN_FALLBACK or track.video:
        return None
    found = await saavn.search(_clean_title(track.title), 1)
    if found and found[0].stream_url:
        log.info("using JioSaavn fallback for %s", track.title)
        return found[0].stream_url
    return None


async def get_source(track: Track) -> str | None:
    """Returns a URL or local path for ffmpeg, or None if the track can't be played."""
    if track.source == "file":
        return track.stream_url if os.path.exists(track.stream_url) else None
    if track.source == "saavn":
        sid = track.url.removeprefix("saavn:")
        return await saavn.stream_url(sid) or track.stream_url or None
    if track.source == "query":
        real = await music_search.materialize(track)
        if not real:
            return None
        track.url, track.source, track.duration, track.thumbnail = real.url, real.source, real.duration, real.thumbnail
        track.stream_url = real.stream_url
        return await get_source(track)
    track.error = ""
    src = await _youtube_source(track)
    if src:
        return src
    err = track.error
    src = await _saavn_fallback(track)
    track.error = "" if src else (err or "failed")
    return src


def purge_cache(max_age: int | None = None, keep: set[str] | None = None) -> int:
    """Delete cached files older than max_age seconds (0 = everything). Returns count removed."""
    max_age = config.CACHE_MAX_AGE if max_age is None else max_age
    removed = 0
    if not os.path.isdir(config.CACHE_DIR):
        return 0
    now = time.time()
    for name in os.listdir(config.CACHE_DIR):
        path = os.path.join(config.CACHE_DIR, name)
        if keep and path in keep:
            continue
        try:
            if os.path.isfile(path) and (max_age == 0 or now - os.path.getmtime(path) > max_age):
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


async def purge_loop(in_use):
    """Hourly cleanup; `in_use()` returns paths that are currently playing."""
    while True:
        await asyncio.sleep(3600)
        try:
            purge_cache(keep=in_use())
        except Exception:
            log.exception("cache purge")
