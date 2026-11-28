"""Shared yt-dlp plumbing: cookies jar, SOCKS5 proxies (then direct), thread offloading."""
import asyncio

import config
import logging
import shutil

import yt_dlp

from services import cookie_manager, proxy_manager

log = logging.getLogger("ytdlp")


def js_runtime() -> str | None:
    """YouTube's signature/'n' challenges need a JavaScript runtime. Deno is installed in the Docker image."""
    for name in ("deno", "node", "bun"):
        if shutil.which(name):
            return name
    return None


def base_opts(proxy: str | None = None, jar: str | None = None) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "geo_bypass": True, "socket_timeout": 20, "retries": 2,
            "remote_components": ["ejs:github"]}  # challenge-solver scripts (also bundled with yt-dlp[default])
    runtime = js_runtime()
    if runtime:
        opts["js_runtimes"] = {runtime: {}}
    if proxy:
        opts["proxy"] = proxy_manager.for_ytdlp(proxy)
    if jar:
        opts["cookiefile"] = jar
    return opts


async def _attempt(work, jar, use_proxy):
    last: Exception | None = None
    tried: set[int] = set()
    attempts: list[tuple[int | None, str | None]] = []
    if use_proxy and config.YTDLP_USE_PROXY:
        for _ in range(2):
            picked = await proxy_manager.pick(exclude=tried)
            if not picked:
                break
            tried.add(picked[0])
            attempts.append(picked)
    attempts.append((None, None))
    for pid, url in attempts:
        try:
            return await asyncio.to_thread(work, base_opts(url, jar)), pid
        except Exception as e:
            last = e
            if pid is not None:
                log.info("yt-dlp via proxy #%s failed: %s", pid, str(e)[:120])
                asyncio.create_task(proxy_manager.report_failure(pid))
    raise last  # type: ignore[misc]


async def run(work, use_proxy: bool = True):
    """work(opts) -> result (sync, runs in a thread). Tries up to 2 proxies, then a direct connection.

    With several YouTube accounts saved they take turns; an account that gets "sign in / not a bot"
    rests for 30 minutes and the next one is tried. Returns (result, proxy_id_used | None).
    """
    from services import audio_provider

    accounts: list[str | None] = cookie_manager.rotation(await cookie_manager.youtube_services()) or [None]
    last: Exception | None = None
    for account in accounts:
        jar = await cookie_manager.make_jar(account)
        try:
            result = await _attempt(work, jar, use_proxy)
            if account:
                cookie_manager.mark_ok(account)
            return result
        except Exception as e:
            last = e
            if account and audio_provider.classify(e) == "blocked":
                log.warning("YouTube account %s blocked, trying the next", cookie_manager.yt_label(account))
                cookie_manager.mark_blocked(account)
                continue
            raise
        finally:
            cookie_manager.cleanup(jar)
    raise last  # type: ignore[misc]
