"""Turns a Track into something ffmpeg can read: a direct URL or a cached local file."""
import asyncio
import contextvars
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
    if any(k in text for k in ("signature solving failed", "n challenge solving failed", "only images are available",
                               "no supported javascript runtime", "challenge solving failed")):
        return "js"
    if any(k in text for k in ("video unavailable", "private video", "has been removed", "not available in your country",
                               "age-restricted", "members-only", "premieres in")):
        return "unavailable"
    return "failed"


async def _alert_blocked(kind: str = "blocked"):
    global _last_alert
    now = time.time()
    if alert_hook is None or now - _last_alert < ALERT_EVERY:
        return
    _last_alert = now
    try:
        if kind == "js":
            text = ("⚠️ <b>yt-dlp can't solve YouTube's JavaScript challenge.</b>\n"
                    "The Deno runtime is missing or yt-dlp is outdated. Rebuild the image "
                    "(<code>docker compose build --no-cache</code>) and run /diag.")
        else:
            text = ("⚠️ <b>YouTube is blocking this server.</b>\n"
                    "Songs can't be fetched until you add a working YouTube <b>cookie</b> or a <b>proxy</b>.\n"
                    "Open the owner panel → 🍪 Cookies (use 🔍 Test) / 🧦 Proxies. (JioSaavn keeps working as a fallback.)")
        await alert_hook(text)
    except Exception:
        log.exception("owner alert")


def _filter():
    return yt_dlp.utils.match_filter_func(f"!is_live & duration<?{config.MAX_DOWNLOAD_SECONDS}")


def _fmt(video: bool) -> str:
    if video:
        h = config.VIDEO_MAX_HEIGHT
        return f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
    # AAC/m4a (~128k) is the smallest good stream: fewer bytes = faster start
    # never fall back to "best": when YouTube offers no audio-only stream that is the full HD video (70+ MB).
    # The smallest stream that has sound is enough, the call ignores the picture anyway.
    return "bestaudio[ext=m4a]/bestaudio/worst[acodec!=none]/worst"


# async callback(percent, speed_bps, eta) set by the player while a track loads
progress_cb: contextvars.ContextVar = contextvars.ContextVar("progress_cb", default=None)


def _progress_hook():
    """yt-dlp progress hook that forwards to the player's callback (thread-safe, throttled)."""
    cb = progress_cb.get()
    if cb is None:
        return None
    loop = asyncio.get_running_loop()
    last = [0.0]

    def hook(d):
        if d.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - last[0] < 1.5:
            return
        last[0] = now
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        pct = int((d.get("downloaded_bytes") or 0) * 100 / total) if total else 0
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(cb(min(pct, 99), d.get("speed"), d.get("eta"))))
    return hook


def _download_work(url: str, video: bool, track: Track | None = None):
    hook = _progress_hook()

    def work(opts):
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        o = {**opts, "format": _fmt(video), "noplaylist": True,
             "outtmpl": os.path.join(config.CACHE_DIR, "%(id)s.%(ext)s"),
             "match_filter": _filter(), "continuedl": True,
             "concurrent_fragment_downloads": 4, "http_chunk_size": 10485760}
        if hook:
            o["progress_hooks"] = [hook]
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise RuntimeError("filtered")
            _learn(track, info)
            path = ydl.prepare_filename(info)
            try:
                size = os.path.getsize(path) / 1048576
            except OSError:
                size = 0
            log.info("downloaded %s: format %s (%s, %s) %.1f MB", info.get("id"), info.get("format_id"),
                     info.get("acodec"), info.get("vcodec"), size)
            return path
    return work


def _learn(track: Track | None, info: dict):
    """Fill in what the search/link step could not know (duration for the progress bar, thumbnail)."""
    if track is None:
        return
    if not track.duration and info.get("duration"):
        track.duration = int(info["duration"])
    if not track.thumbnail and info.get("thumbnail"):
        track.thumbnail = info["thumbnail"]


def _extract_work(url: str, video: bool, track: Track | None = None):
    def work(opts):
        o = {**opts, "format": _fmt(video), "noplaylist": True, "skip_download": True, "match_filter": _filter()}
        with yt_dlp.YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or not info.get("url"):
                raise RuntimeError("no stream url")
            _learn(track, info)
            return info["url"]
    return work


STREAM_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0 Safari/537.36")


async def _url_playable(url: str) -> bool:
    """Cheap check (first byte only) that ffmpeg will really be able to read this stream URL."""
    import aiohttp

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as sess:
            async with sess.get(url, headers={"Range": "bytes=0-1", "User-Agent": STREAM_UA}) as r:
                return r.status in (200, 206)
    except Exception:
        return True  # can't tell: let ffmpeg try


_direct_fails = 0


async def _youtube_source(track: Track) -> str | None:
    global _direct_fails
    # stream URLs are locked to the IP that requested them, so with proxies in use the file is
    # downloaded through the proxy and played from disk. Without proxies, stream the URL directly.
    use_proxy = config.YTDLP_USE_PROXY and bool(await proxy_manager.pick())
    try:
        if use_proxy or track.video or _direct_fails >= 2:
            path, _ = await ytdlp_util.run(_download_work(track.url, track.video, track))
            return path if os.path.exists(path) else None
        url, _ = await ytdlp_util.run(_extract_work(track.url, False, track), use_proxy=False)
        if url and not await _url_playable(url):
            # a stream URL that answers 403/404 gives a silent call ("assistant joined, no sound"): download instead
            _direct_fails += 1  # after 2 misses go straight to download (saves a wasted extraction)
            log.info("direct stream URL not playable; downloading %s", track.url)
            path, _ = await ytdlp_util.run(_download_work(track.url, False, track))
            return path if os.path.exists(path) else None
        _direct_fails = 0
        return url
    except Exception as e:
        track.error = classify(e)
        log.info("youtube source failed (%s): %s", track.error, str(e)[:160])
        if track.error in ("blocked", "js"):
            await _alert_blocked(track.error)
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


_warm: dict[str, tuple[float, str]] = {}  # track url -> (when, source) resolved ahead of time
_warming: set[str] = set()


async def prefetch(track: Track):
    """Resolve the next track's audio while the current one plays, so Skip / auto-advance start instantly."""
    key = track.url
    if not key or track.source not in ("youtube",) or key in _warm or key in _warming:
        return
    _warming.add(key)
    try:
        src = await get_source(track)
        if src:
            _warm[key] = (time.time(), src)
            for k in [k for k, (t, _) in _warm.items() if time.time() - t > 1800]:
                _warm.pop(k, None)
    except Exception:
        pass
    finally:
        _warming.discard(key)


async def get_source(track: Track) -> str | None:
    """Returns a URL or local path for ffmpeg, or None if the track can't be played."""
    hit = _warm.pop(track.url, None) if track.url else None
    if hit and time.time() - hit[0] < 1800 and (hit[1].startswith("http") or os.path.exists(hit[1])):
        return hit[1]
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


async def daily_clean_loop(in_use, hour: int = 3, tz: str = "Asia/Kolkata"):
    """Every day at 03:00 India time: delete all cached audio/video except what is playing right now."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    while True:
        now = datetime.now(zone)
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            n = purge_cache(0, keep=in_use())
            log.info("daily cache clean at %s: removed %s files", hour, n)
        except Exception:
            log.exception("daily cache clean")
