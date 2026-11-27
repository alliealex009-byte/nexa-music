"""Turn links from many streaming platforms into searchable "Artist - Title" text.

Platforms whose audio can't be streamed (Spotify, Apple Music, Deezer, Tidal, Amazon Music,
Gaana, Wynk, Resso, ...) are read only for their public metadata; the audio itself comes from
YouTube (or JioSaavn). yt-dlp handles YouTube, SoundCloud, Bandcamp, Mixcloud, etc. directly.
"""
import html
import json
import logging
import re
from urllib.parse import urlsplit

import aiohttp

from database import credentials as cred
from services import cookie_manager

log = logging.getLogger("links")

META_HOSTS = {
    "open.spotify.com": "spotify", "spotify.link": "spotify", "spotify.com": "spotify",
    "music.apple.com": "apple", "itunes.apple.com": "apple",
    "deezer.com": "deezer", "deezer.page.link": "deezer", "link.deezer.com": "deezer",
    "tidal.com": "tidal", "listen.tidal.com": "tidal",
    "music.amazon.com": "amazon", "music.amazon.in": "amazon",
    "gaana.com": "gaana", "wynk.in": "wynk", "wynkmusic.co": "wynk",
    "resso.com": "resso", "m.resso.com": "resso", "music.yandex.ru": "yandex",
    "pandora.com": "pandora", "napster.com": "napster", "audiomack.com": "audiomack",
}
SAAVN_HOSTS = ("jiosaavn.com", "saavn.com")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def platform(url: str) -> str | None:
    host = host_of(url)
    if any(host == h or host.endswith("." + h) for h in SAAVN_HOSTS):
        return "saavn"
    for h, name in META_HOSTS.items():
        if host == h or host.endswith("." + h):
            return name
    return None


async def _fetch(url: str, headers: dict | None = None) -> str:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": UA, **(headers or {})}) as s:
        async with s.get(url, allow_redirects=True) as r:
            r.raise_for_status()
            return await r.text()


async def _fetch_json(url: str):
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            return await r.json(content_type=None)


def _meta(page: str, prop: str) -> str:
    for pat in (
        rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(prop)}"',
    ):
        m = re.search(pat, page, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _jsonld(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def _clean(text: str) -> str:
    text = re.sub(r"\s+(on|\|)\s+(Spotify|Apple Music|Deezer|TIDAL|Amazon Music|Gaana|Wynk).*$", "", text, flags=re.I)
    text = re.sub(r"\s*[-–|]\s*(song|single|album|EP|playlist)\b.*$", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -–|")


def _from_og(page: str) -> str | None:
    title = _clean(_meta(page, "og:title"))
    if not title:
        return None
    desc = _meta(page, "og:description")
    artist = ""
    m = re.match(r"^(.*?)\s*[·•]\s*", desc)  # Spotify: "Artist · Song · 2020"
    if m:
        artist = m.group(1)
    elif desc.lower().startswith("song by "):
        artist = re.sub(r"^song by\s+", "", desc, flags=re.I).split(" on ")[0].split("·")[0].strip()
    if artist and artist.lower() not in title.lower():
        return f"{artist} - {title}"
    return title


async def _spotify_header() -> dict:
    cookie = cookie_manager.header_for(await cred.get_cookies("spotify"))
    return {"Cookie": cookie} if cookie else {}


async def _spotify_collection(kind: str, ident: str, limit: int) -> list[str]:
    """Track names of a playlist/album from Spotify's public embed page."""
    try:
        page = await _fetch(f"https://open.spotify.com/embed/{kind}/{ident}", await _spotify_header())
    except Exception:
        return []
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    names: list[str] = []

    def walk(node):
        if len(names) >= limit:
            return
        if isinstance(node, dict):
            if "title" in node and "subtitle" in node and isinstance(node["title"], str):
                names.append(f"{node['subtitle']} - {node['title']}")
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return names[:limit]


async def _deezer(url: str, limit: int) -> list[str]:
    if "link.deezer.com" in url or "page.link" in url:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url, allow_redirects=True) as r:
                url = str(r.url)
    m = re.search(r"/(track|album|playlist)/(\d+)", url)
    if not m:
        return []
    kind, ident = m.groups()
    data = await _fetch_json(f"https://api.deezer.com/{kind}/{ident}")
    if kind == "track":
        return [f"{data['artist']['name']} - {data['title']}"]
    items = (data.get("tracks") or {}).get("data", [])[:limit]
    return [f"{t['artist']['name']} - {t['title']}" for t in items]


async def _apple_collection(page: str, limit: int) -> list[str]:
    names = []
    for block in _jsonld(page):
        for t in block.get("track", []) if isinstance(block, dict) else []:
            name = t.get("name")
            artist = ((t.get("byArtist") or [{}])[0] if isinstance(t.get("byArtist"), list) else t.get("byArtist") or {}).get("name", "")
            if name:
                names.append(f"{artist} - {name}" if artist else name)
    return names[:limit]


async def to_queries(url: str, limit: int) -> list[str]:
    """Searchable 'Artist - Title' strings for a link (one for a track, several for a collection)."""
    plat = platform(url)
    try:
        if plat == "deezer":
            return await _deezer(url, limit)
        m = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?(playlist|album)/([A-Za-z0-9]+)", url)
        if m:
            found = await _spotify_collection(m.group(1), m.group(2), limit)
            if found:
                return found
        page = await _fetch(url, await _spotify_header() if plat == "spotify" else None)
        if plat == "apple":
            multi = await _apple_collection(page, limit)
            if len(multi) > 1:
                return multi
            if "?i=" in url or "/song/" in url:
                one = _from_og(page)
                return [one] if one else []
        one = _from_og(page)
        return [one] if one else []
    except Exception as e:
        log.info("link %s failed: %s", plat, type(e).__name__)
        return []
