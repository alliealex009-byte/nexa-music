"""Lyrics from LRCLIB (community database, no key needed)."""
import logging
import re

import aiohttp

import config

log = logging.getLogger("lyrics")


def clean_title(title: str) -> str:
    title = re.sub(r"\(.*?\)|\[.*?\]", " ", title)
    title = re.sub(r"\b(official|music|video|audio|lyrics?|lyrical|hd|4k|full song|ft\.?.*|feat\.?.*)\b", " ", title, flags=re.I)
    title = re.sub(r"\|.*$", " ", title)
    return re.sub(r"\s+", " ", title).strip(" -–")


async def _get(path: str, params: dict):
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"User-Agent": "nexa-music-bot (telegram)"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
        async with s.get(f"{config.LYRICS_API_BASE}{path}", params=params) as r:
            if r.status == 404:
                return None
            r.raise_for_status()
            return await r.json(content_type=None)


async def find(query: str) -> tuple[str, str] | None:
    """Returns (heading, plain lyrics) or None."""
    query = clean_title(query)
    if not query:
        return None
    try:
        results = await _get("/search", {"q": query}) or []
    except Exception as e:
        log.info("lyrics search failed: %s", type(e).__name__)
        return None
    for item in results:
        text = (item.get("plainLyrics") or "").strip()
        if text:
            return f"{item.get('artistName', '')} - {item.get('trackName', '')}".strip(" -"), text
    return None


_LRC = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[tuple[float, str]]:
    """'[01:23.45] some words' lines -> sorted [(seconds, words)]; empty lines are kept as pauses."""
    out = []
    for line in (text or "").splitlines():
        stamps = list(_LRC.finditer(line))
        if not stamps:
            continue
        words = line[stamps[-1].end():].strip()
        for m in stamps:
            frac = float("0." + m.group(3)) if m.group(3) else 0.0
            out.append((int(m.group(1)) * 60 + int(m.group(2)) + frac, words))
    return sorted(out)


def line_at(lines: list[tuple[float, str]], position: float) -> str:
    """The lyric line that is being sung at `position` seconds ('' before the first line / in a pause)."""
    current = ""
    for ts, words in lines:
        if ts > position:
            break
        current = words
    return current


async def find_synced(query: str, duration: int = 0) -> list[tuple[float, str]]:
    """Time-stamped lyrics for karaoke mode ([] if the database has none)."""
    query = clean_title(query)
    if not query:
        return []
    try:
        results = await _get("/search", {"q": query}) or []
    except Exception as e:
        log.info("synced lyrics search failed: %s", type(e).__name__)
        return []
    best = None
    for item in results:
        if not (item.get("syncedLyrics") or "").strip():
            continue
        gap = abs((item.get("duration") or 0) - duration) if duration else 0
        if best is None or gap < best[0]:
            best = (gap, item["syncedLyrics"])
        if gap <= 3:
            break
    return parse_lrc(best[1]) if best else []
