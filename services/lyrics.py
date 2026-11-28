"""Lyrics from LRCLIB (community database, no key needed)."""
import asyncio
import logging
import re

import aiohttp

import config

log = logging.getLogger("lyrics")


def clean_title(title: str) -> str:
    title = re.sub(r"\(.*?\)|\[.*?\]", " ", title)
    title = re.sub(r"\b(official|music|video|audio|lyrics?|lyrical|hd|4k|full|song|new|ft\.?.*|feat\.?.*)\b", " ", title, flags=re.I)
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


_NOISE = re.compile(r"\b(official|music|video|audio|lyrics?|lyrical|hd|4k|full|song|new|ft|feat)\b", re.I)


def _tokens(text: str) -> set[str]:
    """Words of a title. Unlike clean_title this keeps everything after a '|' (that is where YouTube titles put
    the song name: 'KK | Dil Ibaadat Kar Raha Hai | Emraan Hashmi')."""
    text = _NOISE.sub(" ", re.sub(r"\(.*?\)|\[.*?\]", " ", text))
    return {t for t in re.split(r"[\s_\-|~,.:;/()\[\]&+'\"!?]+", text.lower()) if len(t) > 1}


def _score(item: dict, want: set[str], duration: int | None) -> float:
    """How well a result matches what was asked: its title words must appear in the request (that is what
    separates the right song from a fuzzy neighbour), artist words and song length refine the ranking."""
    name = _tokens(item.get("trackName", ""))
    have = name | _tokens(item.get("artistName", ""))
    if not want or not have:
        return 0.0
    artist = _tokens(item.get("artistName", ""))
    if len(name) == 1 and len(want) > 2 and not (artist & want):
        return -1.0  # a one-word title ("kk") matches any long request; only trust it if the artist matches too
    cover = len(want & name) / len(name) if name else len(want & have) / len(have)
    score = cover + 0.3 * len(want & have) / len(want)
    if duration and item.get("duration"):
        diff = abs(float(item["duration"]) - duration)
        score += 0.5 if diff <= 4 else 0.25 if diff <= 10 else -0.4 if diff > 30 else 0
    return score


def allowed_script(text: str, share: float = 0.92) -> bool:
    """Only English / Hinglish (Latin) and Hindi (Devanagari) lyrics: no Russian, Arabic, CJK... wrong-song results."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ok = sum(1 for c in letters if c < "\u0250" or "\u0900" <= c <= "\u097F")
    return ok / len(letters) >= share


def _queries(raw: str) -> list[str]:
    """Search phrasings: each '|'-separated part with 2+ words (the song name is one of them), then the whole
    title. lrclib returns nothing when a query has too many words, so the long one is capped."""
    plain = re.sub(r"\(.*?\)|\[.*?\]", " ", raw)
    parts = [re.sub(r"\s+", " ", _NOISE.sub(" ", p)).strip(" -") for p in re.split(r"[|~–—]|\s-\s", plain)]
    whole = " ".join(re.sub(r"\s+", " ", _NOISE.sub(" ", plain.replace("|", " "))).split()[:8])
    out = []
    for q in [p for p in parts if len(p.split()) >= 2][:3] + [whole]:
        if q and q not in out:
            out.append(q)
    return out


async def _search(raw: str) -> list:
    """Results of every phrasing together (the ranking picks the right one), de-duplicated."""
    async def one(q):
        try:
            return await _get("/search", {"q": q}) or []
        except Exception as e:
            log.info("lyrics search failed: %s", type(e).__name__)
            return []

    merged, seen = [], set()
    for batch in await asyncio.gather(*[one(q) for q in _queries(raw)]):
        for item in batch:
            key = item.get("id") or (item.get("trackName"), item.get("artistName"), item.get("duration"))
            if key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


async def find(query: str, duration: int | None = None) -> tuple[str, str] | None:
    """Returns (heading, plain lyrics) or None. The best-matching result wins (title words + song length),
    and a result that barely resembles the song is rejected instead of showing the wrong lyrics."""
    if not clean_title(query):
        return None
    results = await _search(query)
    want = _tokens(query)
    ranked = sorted((r for r in results if (r.get("plainLyrics") or "").strip()),
                    key=lambda r: _score(r, want, duration), reverse=True)
    ranked = [r for r in ranked if allowed_script(r["plainLyrics"]) and _score(r, want, duration) >= 0.6]
    if not ranked:
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
    if not clean_title(query):
        return []
    results = await _search(query)
    want = _tokens(query)
    ranked = sorted((r for r in results if (r.get("syncedLyrics") or "").strip()),
                    key=lambda r: _score(r, want, duration or None), reverse=True)
    ranked = [r for r in ranked if allowed_script(r["syncedLyrics"]) and _score(r, want, duration or None) >= 0.6]
    return parse_lrc(ranked[0]["syncedLyrics"]) if ranked else []
