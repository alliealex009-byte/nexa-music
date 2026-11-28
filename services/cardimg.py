"""Pillow-rendered cards (now playing, queued, ping, welcome). Everything degrades gracefully:
render_* return JPEG bytes, or None if Pillow / the picture is unavailable, and callers fall back to a plain photo."""
import asyncio
import io
import logging
import os
import time

import aiohttp

log = logging.getLogger("cardimg")

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except Exception:  # pragma: no cover
    Image = None

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
W, H = 1280, 720
ACCENT = (255, 94, 120)
_cache: dict[str, tuple[float, bytes]] = {}
_session: aiohttp.ClientSession | None = None


def _font(size: int, bold: bool = False):
    for name in ("Inter-Bold.otf" if bold else "Inter-Regular.otf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
        for base in (FONT_DIR, "/usr/share/fonts/truetype/dejavu"):
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
    return ImageFont.load_default()


async def fetch(url: str, timeout: float = 4.0) -> bytes | None:
    """Download a picture (cached for 10 minutes). Never raises."""
    if not url or not url.startswith("http"):
        if url and os.path.exists(url):
            try:
                with open(url, "rb") as f:
                    return f.read()
            except Exception:
                return None
        return None
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    global _session
    try:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
        async with _session.get(url) as r:
            if r.status != 200:
                return None
            data = await r.read()
    except Exception as e:
        log.info("thumbnail fetch failed: %s", e)
        return None
    if len(_cache) > 60:
        _cache.clear()
    _cache[url] = (time.time(), data)
    return data


def _open(data: bytes | None):
    if not data or Image is None:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _background(img):
    bg = ImageOps.fit(img, (W, H)).filter(ImageFilter.GaussianBlur(38))
    return Image.blend(bg, Image.new("RGB", (W, H), (10, 10, 16)), 0.55)


def _rounded(img, size: int, radius: int):
    img = ImageOps.fit(img, (size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius, fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0))
    out.putalpha(mask)
    return out


def _fit_text(draw, text: str, font_fn, max_w: int, size: int, bold=True, min_size=30):
    while size > min_size:
        f = font_fn(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return text, f
        size -= 4
    f = font_fn(min_size, bold)
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…", f


def _clock(sec: int) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _jpeg(img) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _canvas(cover_bytes: bytes | None, fallback_bytes: bytes | None = None):
    cover = _open(cover_bytes) or _open(fallback_bytes)
    if cover is None:
        cover = Image.new("RGB", (600, 600), (40, 40, 60))
        d = ImageDraw.Draw(cover)
        d.ellipse((150, 150, 450, 450), outline=ACCENT, width=14)
        d.ellipse((270, 270, 330, 330), fill=ACCENT)
    return _background(cover), cover


def render_player(cover: bytes | None, title: str, subtitle: str, duration: int, paused: bool = False,
                  fallback: bytes | None = None, position: int = 0) -> bytes | None:
    """The 'Streaming in VC' card: blurred backdrop, big cover, title, who asked, and a progress bar."""
    if Image is None:
        return None
    try:
        bg, art = _canvas(cover, fallback)
        d = ImageDraw.Draw(bg)
        bg.paste(_rounded(art, 520, 36), (90, 100), _rounded(art, 520, 36))
        x = 680
        d.text((x, 130), "PAUSED" if paused else "NOW STREAMING", font=_font(30, True), fill=ACCENT)
        t, f = _fit_text(d, title, _font, W - x - 70, 64)
        d.text((x, 190), t, font=f, fill="white")
        s, sf = _fit_text(d, subtitle, _font, W - x - 70, 34, bold=False, min_size=24)
        d.text((x, 280), s, font=sf, fill=(200, 200, 210))
        by = 470
        bar_w = W - 70 - x
        frac = min(1.0, max(0.0, position / duration)) if duration else 0.0
        fill = max(14, int(bar_w * frac))
        d.rounded_rectangle((x, by, W - 70, by + 10), 5, fill=(110, 110, 125))
        d.rounded_rectangle((x, by, x + fill, by + 10), 5, fill=ACCENT)
        d.ellipse((x + fill - 9, by - 9, x + fill + 9, by + 19), fill="white")
        d.text((x, by + 30), _clock(position), font=_font(28), fill=(220, 220, 230))
        end = _clock(duration) if duration else "LIVE"
        d.text((W - 70 - d.textlength(end, font=_font(28)), by + 30), end, font=_font(28), fill=(220, 220, 230))
        d.text((x, 600), "RIA MUSIC", font=_font(26, True), fill=(255, 255, 255, 120))
        return _jpeg(bg)
    except Exception:
        log.exception("render_player")
        return None


def render_queue(cover: bytes | None, title: str, requested_by: str, number: int, in_line: int, starts_in: str,
                 fallback: bytes | None = None) -> bytes | None:
    if Image is None:
        return None
    try:
        bg, art = _canvas(cover, fallback)
        d = ImageDraw.Draw(bg)
        d.rounded_rectangle((70, 70, W - 70, H - 70), 40, fill=(0, 0, 0))
        bg2 = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.35)
        bg.paste(bg2)
        d = ImageDraw.Draw(bg)
        d.text((120, 110), f"QUEUED  #{number:02d}", font=_font(54, True), fill="white")
        d.text((120, 185), f"{in_line} IN LINE  |  STARTS IN {starts_in}", font=_font(30), fill=ACCENT)
        d.rounded_rectangle((120, 270, W - 120, 560), 28, fill=(20, 20, 28))
        mask = _rounded(art, 220, 24)
        bg.paste(mask, (150, 305), mask)
        t, f = _fit_text(d, title, _font, W - 520, 46, min_size=30)
        d.text((410, 340), t, font=f, fill="white")
        d.text((410, 415), f"Requested by {requested_by}", font=_font(30, False), fill=(190, 190, 200))
        return _jpeg(bg)
    except Exception:
        log.exception("render_queue")
        return None


def render_ping(base: bytes | None, latency_ms: int, uptime: str, status: str = "ONLINE") -> bytes | None:
    if Image is None:
        return None
    try:
        bg, _ = _canvas(base)
        d = ImageDraw.Draw(bg)
        d.text((90, 90), "RIA MUSIC", font=_font(40, True), fill=ACCENT)
        d.text((90, 250), f"{latency_ms} ms", font=_font(170, True), fill="white")
        d.text((96, 450), f"UPTIME {uptime}   |   {status}", font=_font(40), fill=(220, 220, 230))
        return _jpeg(bg)
    except Exception:
        log.exception("render_ping")
        return None


def render_welcome(avatar: bytes | None, name: str, user_id: int, username: str | None, chat_title: str = "",
                   base: bytes | None = None) -> bytes | None:
    if Image is None:
        return None
    try:
        bg, art = _canvas(base or avatar)
        d = ImageDraw.Draw(bg)
        d.text((90, 100), "WELCOME", font=_font(44, True), fill=ACCENT)
        pic = _open(avatar)
        if pic is not None:
            size = 360
            circ = ImageOps.fit(pic, (size, size))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            bg.paste(circ, (90, 190), mask)
        x = 520
        t, f = _fit_text(d, name, _font, W - x - 70, 80)
        d.text((x, 220), t, font=f, fill="white")
        d.text((x, 340), f"ID  {user_id}", font=_font(38, False), fill=(210, 210, 220))
        d.text((x, 400), f"@{username}" if username else "no username", font=_font(38, False), fill=(210, 210, 220))
        if chat_title:
            c, cf = _fit_text(d, chat_title, _font, W - x - 70, 34, bold=False, min_size=24)
            d.text((x, 560), c, font=cf, fill=ACCENT)
        return _jpeg(bg)
    except Exception:
        log.exception("render_welcome")
        return None


async def render(fn, *args, **kwargs):
    """Rendering is CPU work: keep it off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)
