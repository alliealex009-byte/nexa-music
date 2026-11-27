"""Proxy pool (socks5/socks4/http): add/remove, health checks, automatic removal of dead proxies."""
import asyncio
import itertools
import logging
import re
import time
from urllib.parse import quote, unquote, urlsplit

import aiohttp

import config
from database import credentials as cred

log = logging.getLogger("proxy")

_rr = itertools.count()
_notify = None  # async callable(text) -> owner notification
_task = None


class ProxyError(ValueError):
    pass


SCHEMES = {"socks5": "socks5", "socks5h": "socks5", "socks4": "socks4", "socks4a": "socks4", "http": "http", "https": "http"}


def normalize(raw: str) -> str:
    """Accepts host:port, host:port:user:pass, user:pass@host:port and socks5/socks4/http URLs.
    A trailing comment such as '  # 49ms' (as in pasted proxy lists) is ignored."""
    raw = re.sub(r"\s+#.*$", "", (raw or "").strip()).strip()
    if not raw or raw.startswith("#"):
        raise ProxyError("Empty proxy.")
    scheme = "socks5"
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        scheme = SCHEMES.get(scheme.lower())
        if not scheme:
            raise ProxyError("Unsupported proxy type (use socks5://, socks4:// or http://).")
    else:
        rest = raw
    user = password = None
    parts = rest.split(":")
    if len(parts) >= 4 and parts[1].isdigit() and "@" not in parts[0]:
        # host:port:user:pass (the password may itself contain @ or :)
        hostport, user, password = f"{parts[0]}:{parts[1]}", parts[2], ":".join(parts[3:])
    elif "@" in rest:
        creds, hostport = rest.rsplit("@", 1)
        user, _, password = creds.partition(":")
    elif len(parts) == 2:
        hostport = rest
    else:
        raise ProxyError("Format: host:port, host:port:user:pass or socks5://user:pass@host:port")
    m = re.fullmatch(r"([A-Za-z0-9.\-]+|\[[0-9a-fA-F:]+\]):(\d{1,5})", hostport)
    if not m or not 0 < int(m.group(2)) < 65536:
        raise ProxyError("Invalid host:port.")
    auth = ""
    if user:
        auth = quote(unquote(user), safe="") + (":" + quote(unquote(password), safe="") if password else "") + "@"
    return f"{scheme}://{auth}{m.group(1)}:{m.group(2)}"


def mask(url: str) -> str:
    p = urlsplit(url)
    host = f"{p.hostname}:{p.port}"
    return f"{p.scheme}://{p.username}:***@{host}" if p.username else f"{p.scheme}://{host}"


def for_ytdlp(url: str) -> str:
    """yt-dlp: socks5h makes DNS resolve through the proxy."""
    return url.replace("socks5://", "socks5h://", 1)


async def check(url: str) -> tuple[bool, int]:
    """Fetch PROXY_TEST_URL through the proxy. Returns (ok, latency_ms)."""
    from aiohttp_socks import ProxyConnector

    started = time.monotonic()
    try:
        connector = ProxyConnector.from_url(url, rdns=True)
        timeout = aiohttp.ClientTimeout(total=config.PROXY_TIMEOUT)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as s:
            async with s.get(config.PROXY_TEST_URL, allow_redirects=False) as r:
                ok = r.status < 400
    except Exception as e:
        log.info("proxy check failed (%s): %s", mask(url), type(e).__name__)
        return False, 0
    return ok, int((time.monotonic() - started) * 1000)


async def add(raw: str) -> tuple[str, str]:
    """Validate + health-check + store. Returns (status, masked) with status ok|dead|duplicate."""
    url = normalize(raw)
    ok, ms = await check(url)
    if not ok:
        return "dead", mask(url)
    pid = await cred.add_proxy(url)
    if pid is None:
        return "duplicate", mask(url)
    await cred.record_proxy_ok(pid, ms)
    return "ok", mask(url)


async def _handle_result(pid: int, url: str, ok: bool, ms: int) -> bool:
    """Record a check. Returns True if the proxy was removed."""
    if ok:
        await cred.record_proxy_ok(pid, ms)
        return False
    fails = await cred.record_proxy_fail(pid)
    if fails >= config.PROXY_MAX_FAILS:
        await cred.remove_proxy(pid)
        log.warning("removed dead proxy %s", mask(url))
        if _notify:
            try:
                await _notify(f"🗑 Removed dead proxy <code>{mask(url)}</code> after {fails} failed checks.")
            except Exception:
                pass
        return True
    return False


async def check_all() -> tuple[int, int]:
    """Check every stored proxy. Returns (alive, removed)."""
    rows = await cred.list_proxies()
    results = await asyncio.gather(*(check(url) for _, url, *_ in rows))
    alive = removed = 0
    for (pid, url, *_), (ok, ms) in zip(rows, results):
        if await _handle_result(pid, url, ok, ms):
            removed += 1
        elif ok:
            alive += 1
    return alive, removed


async def pick(exclude: set[int] | None = None) -> tuple[int, str] | None:
    """Round-robin over proxies that passed their last check. Returns (id, url)."""
    rows = [r for r in await cred.list_proxies() if r[2] == 0 and (not exclude or r[0] not in exclude)]
    if not rows:
        return None
    row = rows[next(_rr) % len(rows)]
    return row[0], row[1]


async def report_failure(pid: int):
    """A real download failed through this proxy: re-check it right away (may remove it)."""
    for row in await cred.list_proxies():
        if row[0] == pid:
            ok, ms = await check(row[1])
            await _handle_result(pid, row[1], ok, ms)
            return


async def _loop():
    while True:
        await asyncio.sleep(config.PROXY_CHECK_INTERVAL)
        try:
            if await cred.list_proxies():
                await check_all()
        except Exception:
            log.exception("proxy check loop")


def start(notify=None):
    global _task, _notify
    _notify = notify
    if _task is None or _task.done():
        _task = asyncio.get_event_loop().create_task(_loop())
