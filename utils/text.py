import html
import re


def esc(value) -> str:
    """Escape user-provided text for HTML parse mode."""
    return html.escape(str(value), quote=False)


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def chunk(text: str, size: int = 3500) -> list[str]:
    """Split on line breaks so every piece fits in one Telegram message."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:  # a single huge line
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:size])
            line = line[size:]
        if len(current) + len(line) > size:
            parts.append(current)
            current = ""
        current += line
    if current.strip():
        parts.append(current)
    return parts


def fmt_duration(seconds: int) -> str:
    if not seconds:
        return "Live"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_clock(seconds: int) -> str:
    """Playback position (0 is a valid position, unlike a duration of 0 = live)."""
    m, s = divmod(max(int(seconds), 0), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
