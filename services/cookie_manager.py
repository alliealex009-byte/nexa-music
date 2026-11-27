"""Cookie storage helpers: normalise whatever the owner pastes into a Netscape jar.

Only YouTube cookies and "other:<site>" cookies are handed to yt-dlp. Spotify and
Apple Music cookies are used only when fetching their link pages (never sent elsewhere).
"""
import json
import os
import re
import stat
import tempfile
import time

import config
from database import credentials as cred

ALIASES = {
    "yt": "youtube", "youtube": "youtube", "ytmusic": "youtube", "music.youtube": "youtube",
    "sp": "spotify", "spotify": "spotify",
    "am": "apple", "apple": "apple", "applemusic": "apple", "apple_music": "apple", "apple-music": "apple",
}
DOMAINS = {
    "youtube": ("youtube.com", "google.com"),
    "spotify": ("spotify.com",),
    "apple": ("apple.com",),
}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"


class CookieError(ValueError):
    pass


def resolve_service(name: str) -> str:
    key = (name or "").strip().lower()
    if key.startswith("other:"):
        key = key[6:]
    elif key in ALIASES:
        return ALIASES[key]
    elif key == "other":
        raise CookieError("Name the site, e.g. `other soundcloud`.")
    key = re.sub(r"[^a-z0-9.\-]", "", key)
    if not key:
        raise CookieError("Invalid service name.")
    return f"other:{key[:40]}"


def _domain(line: str) -> str:
    """Cookie domain of a Netscape line, without the HttpOnly marker or leading dot."""
    return line.split("\t")[0].removeprefix("#HttpOnly_").lstrip(".").lower()


def _netscape_line(domain, flag, path, secure, expires, name, value) -> str:
    return "\t".join([domain, flag, path, "TRUE" if secure else "FALSE", str(int(expires or 0)), name, value])


def _from_json(data) -> list[str]:
    if isinstance(data, dict):
        data = data.get("cookies", [data])
    lines = []
    for c in data:
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        domain = c.get("domain") or c.get("host") or ""
        if not domain:
            continue
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        lines.append(
            _netscape_line(domain, flag, c.get("path", "/"), c.get("secure", False),
                           c.get("expirationDate") or c.get("expires") or 0, c["name"], str(c["value"]))
        )
    return lines


def normalize(raw: str, service: str) -> str:
    """Return a Netscape cookie file text, or raise CookieError."""
    raw = (raw or "").strip().lstrip("\ufeff")
    if not raw:
        raise CookieError("Empty cookie data.")
    lines: list[str] = []
    if raw[0] in "[{":
        try:
            lines = _from_json(json.loads(raw))
        except json.JSONDecodeError as e:
            raise CookieError(f"Invalid JSON: {e.msg}")
    elif "\t" in raw:
        for line in raw.splitlines():
            line = line.strip()
            if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            if len(line.split("\t")) == 7:
                lines.append(line)
    elif service == "spotify" and re.fullmatch(r"[A-Za-z0-9_\-\.]{20,}", raw):
        lines = [_netscape_line(".spotify.com", "TRUE", "/", True, int(time.time()) + 365 * 86400, "sp_dc", raw)]
    elif service == "spotify" and re.match(r"sp_dc\s*=", raw):
        value = re.split(r"[;\s]", raw.split("=", 1)[1].strip())[0]
        lines = [_netscape_line(".spotify.com", "TRUE", "/", True, int(time.time()) + 365 * 86400, "sp_dc", value)]
    if not lines:
        raise CookieError(
            "I couldn't read any cookies. Send a Netscape cookies.txt (export it with a browser "
            "extension), a JSON export, or for Spotify just the sp_dc value."
        )
    domains = DOMAINS.get(service)
    if domains:
        ok = [l for l in lines if any(_domain(l).endswith(d) for d in domains)]
        if not ok:
            raise CookieError(f"None of these cookies belong to {' / '.join(domains)}. Wrong file?")
        lines = ok
    return NETSCAPE_HEADER + "\n".join(lines) + "\n"


def summarize(content: str) -> tuple[int, list[str]]:
    domains, count = set(), 0
    for line in content.splitlines():
        parts = line.split("\t")
        if len(parts) == 7:
            count += 1
            domains.add(_domain(line))
    return count, sorted(domains)


def header_for(content: str | None) -> str:
    """Cookie: header value built from a stored jar (for fetching link pages)."""
    if not content:
        return ""
    pairs = []
    for line in content.splitlines():
        parts = line.split("\t")
        if len(parts) == 7:
            pairs.append(f"{parts[5]}={parts[6]}")
    return "; ".join(pairs)


async def make_jar() -> str | None:
    """Write YouTube + other:* cookies to a private temp file for yt-dlp (None if there are none)."""
    chunks = []
    for service, content, _ in await cred.all_cookies():
        if service == "youtube" or service.startswith("other:"):
            chunks.append("\n".join(l for l in content.splitlines() if l and not l.startswith("# Netscape")))
    if not chunks:
        return None
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="ck_", suffix=".txt", dir=config.CACHE_DIR)
    with os.fdopen(fd, "w") as f:
        f.write(NETSCAPE_HEADER + "\n".join(chunks) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


def cleanup(path: str | None):
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


LOGIN_COOKIES = ("SID", "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO")


def login_state(content: str) -> tuple[bool, int, int]:
    """(has a Google login cookie, how many cookies are already expired, total) for a stored YouTube jar."""
    names, expired, total, now = set(), 0, 0, time.time()
    for line in content.splitlines():
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        total += 1
        names.add(parts[5])
        try:
            exp = int(float(parts[4]))
        except ValueError:
            exp = 0
        if exp and exp < now:
            expired += 1
    return bool(names & set(LOGIN_COOKIES)), expired, total


def write_jar(content: str) -> str:
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="ck_", suffix=".txt", dir=config.CACHE_DIR)
    with os.fdopen(fd, "w") as f:
        f.write(content if content.startswith("#") else NETSCAPE_HEADER + content)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path
