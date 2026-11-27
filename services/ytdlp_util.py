"""Shared yt-dlp plumbing: cookies jar, SOCKS5 proxies (then direct), thread offloading."""
import asyncio
import logging

import yt_dlp

from services import cookie_manager, proxy_manager

log = logging.getLogger("ytdlp")


def base_opts(proxy: str | None = None, jar: str | None = None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "geo_bypass": True, "socket_timeout": 20, "retries": 2}
    if proxy:
        opts["proxy"] = proxy_manager.for_ytdlp(proxy)
    if jar:
        opts["cookiefile"] = jar
    return opts


async def run(work, use_proxy: bool = True):
    """work(opts) -> result (sync, runs in a thread). Tries up to 2 proxies, then a direct connection.

    Returns (result, proxy_id_used | None). Raises the last error if everything failed.
    """
    jar = await cookie_manager.make_jar()
    last: Exception | None = None
    tried: set[int] = set()
    try:
        attempts: list[tuple[int | None, str | None]] = []
        if use_proxy:
            for _ in range(2):
                picked = await proxy_manager.pick(exclude=tried)
                if not picked:
                    break
                tried.add(picked[0])
                attempts.append(picked)
        attempts.append((None, None))
        for pid, url in attempts:
            try:
                result = await asyncio.to_thread(work, base_opts(url, jar))
                return result, pid
            except Exception as e:
                last = e
                if pid is not None:
                    log.info("yt-dlp via proxy #%s failed: %s", pid, str(e)[:120])
                    asyncio.create_task(proxy_manager.report_failure(pid))
        raise last  # type: ignore[misc]
    finally:
        cookie_manager.cleanup(jar)
