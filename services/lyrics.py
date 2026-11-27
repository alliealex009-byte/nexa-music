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
