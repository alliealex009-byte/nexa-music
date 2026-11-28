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


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[\s_\-|,.:;/()\[\]&+'\"!?]+", clean_title(text).lower()) if len(t) > 1}


def _score(item: dict, want: set[str], duration: int | None) -> float:
    """How well a result matches what was asked: its title words must appear in the request (that is what
    separates the right song from a fuzzy neighbour), artist words and song length refine the ranking."""
    name = _tokens(item.get("trackName", ""))
    have = name | _tokens(item.get("artistName", ""))
    if not want or not have:
        return 0.0
    cover = len(want & name) / len(name) if name else len(want & have) / len(have)
    score = cover + 0.3 * len(want & have) / len(want)
    if duration and item.get("duration"):
        diff = abs(float(item["duration"]) - duration)
        score += 0.5 if diff <= 4 else 0.25 if diff <= 10 else -0.4 if diff > 30 else 0
    return score


async def find(query: str, duration: int | None = None) -> tuple[str, str] | None:
    """Returns (heading, plain lyrics) or None. The best-matching result wins (title words + song length),
    and a result that barely resembles the song is rejected instead of showing the wrong lyrics."""
    query = clean_title(query)
    if not query:
        return None
    try:
        results = await _get("/search", {"q": query}) or []
    except Exception as e:
        log.info("lyrics search failed: %s", type(e).__name__)
        return None
    want = _tokens(query)
    ranked = sorted((r for r in results if (r.get("plainLyrics") or "").strip()),
                    key=lambda r: _score(r, want, duration), reverse=True)
    if not ranked or _score(ranked[0], want, duration) < 0.6:
        return None
    best = ranked[0]
    return f"{best.get('artistName', '')} - {best.get('trackName', '')}".strip(" -"), best["plainLyrics"].strip()


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
    want = _tokens(query)
    ranked = sorted((r for r in results if (r.get("syncedLyrics") or "").strip()),
                    key=lambda r: _score(r, want, duration or None), reverse=True)
    if not ranked or _score(ranked[0], want, duration or None) < 0.6:
        return []
    return parse_lrc(ranked[0]["syncedLyrics"])
