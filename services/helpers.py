"""Helper (assistant) accounts: start them, brand them, add/remove them at runtime.

A helper is a normal Telegram user account logged in with a session string. It joins the voice chats and streams the
audio. One helper can stream in many groups at the same time; with more helpers the groups are spread over them.
"""
import asyncio
import logging
import os
import random
from urllib.parse import unquote, urlsplit

from pyrogram import Client
from pytgcalls import PyTgCalls

import config
from database import credentials as cred
from services import player, proxy_manager

log = logging.getLogger("helpers")


def tg_proxy_dict(url: str | None) -> dict | None:
    """Pyrogram proxy dict from socks5://user:pass@host:port (None = connect directly)."""
    if not url or url == "-":
        return None
    p = urlsplit(url)
    d = {"scheme": "http" if p.scheme.startswith("http") else p.scheme, "hostname": p.hostname, "port": p.port}
    if p.username:
        d["username"] = unquote(p.username)
        d["password"] = unquote(p.password or "")
    return d


def in_use() -> set[str]:
    return {h.proxy for h in player.helpers() if h.proxy}


async def free_proxy() -> str | None:
    """A healthy proxy no helper account uses yet (accounts never share an IP)."""
    taken = in_use()
    if config.HELPER_PROXIES:
        taken |= {proxy_manager.normalize(x) for x in config.HELPER_PROXIES if x != "-"}
    for row in await cred.list_proxies():
        if row[2] == 0 and row[1] not in taken:
            return row[1]
    return None


def expected_name(index: int) -> str:
    return f"{config.BOT_NAME} {index}"


async def brand(helper: player.Helper, photo: bool = True) -> list[str]:
    """Name = 'Ria Music N', bio = ads-free line, old profile photos removed, new DP set. Returns a report."""
    report = []
    c = helper.client
    try:
        await c.update_profile(first_name=expected_name(helper.index), last_name="", bio=config.HELPER_BIO[:70])
        report.append(f"✅ name «{expected_name(helper.index)}» + bio")
    except Exception as e:
        report.append(f"⚠️ name/bio not changed ({type(e).__name__})")
    if photo and os.path.exists(config.HELPER_DP):
        try:
            has = [p async for p in c.get_chat_photos("me", limit=1)]
            if not has:  # never delete photos: mass profile changes are a freeze trigger
                await c.set_profile_photo(photo=config.HELPER_DP)
                report.append("✅ profile photo set")
            else:
                report.append("ℹ️ already has a photo (kept)")
        except Exception as e:
            report.append(f"⚠️ photo not changed ({type(e).__name__})")
    try:
        await player.helper_me(helper)
    except Exception:
        pass
    return report


async def _start(session: str, source: str, db_id: int | None = None, proxy: str | None = None) -> player.Helper:
    n = len(player.helpers()) + 1
    client = Client(f"ria_helper_{n}", api_id=config.API_ID, api_hash=config.API_HASH, session_string=session,
                    in_memory=True, proxy=tg_proxy_dict(proxy))
    calls = PyTgCalls(client)
    await client.start()
    try:
        await calls.start()
    except Exception:
        await client.stop()
        raise
    helper = player.add_helper(client, calls, source, db_id)
    helper.proxy = proxy
    await player.helper_me(helper)
    return helper


async def start_extra() -> list[str]:
    """Start helpers #2.. from SESSION_STRINGS and the database, one at a time with a pause in between
    (logging many accounts in from one IP in the same second looks like abuse). Returns problems for the owner."""
    problems = []
    seen = {config.SESSION_STRING}
    env_proxies = config.HELPER_PROXIES[1:]
    jobs = []
    for i, sess in enumerate(config.SESSION_STRINGS):
        px = env_proxies[i] if i < len(env_proxies) and env_proxies[i] != "-" else None
        jobs.append((sess, "env", None, proxy_manager.normalize(px) if px else None))
    jobs += [(s, "db", rid, px) for rid, s, px in await cred.list_helper_rows()]
    first = True
    for session, source, db_id, proxy in jobs:
        if session in seen:
            continue
        seen.add(session)
        if len(player.helpers()) >= config.MAX_HELPERS:
            problems.append(f"Helper limit ({config.MAX_HELPERS}) reached; skipped one session.")
            break
        if not first:
            await asyncio.sleep(config.HELPER_START_GAP + random.uniform(0, 5))
        first = False
        try:
            await _start(session, source, db_id, proxy)
        except Exception as e:
            log.warning("helper session failed to start: %s", type(e).__name__)
            problems.append(f"A helper session failed to start ({type(e).__name__}); check or remove it.")
    return problems


async def brand_all(force: bool = False) -> list[str]:
    """At startup: fix names (and the first-time photo) of helpers that aren't branded yet."""
    out = []
    if not config.HELPER_BRANDING and not force:
        return out
    for n, h in enumerate(player.helpers()):
        if force or h.name != expected_name(h.index):
            if n:
                await asyncio.sleep(20 + random.uniform(0, 10))
            out.append(f"{expected_name(h.index)}: " + "; ".join(await brand(h, photo=True)))
    return out


async def add_from_owner(session: str) -> str:
    session = session.strip()
    if len(player.helpers()) >= config.MAX_HELPERS:
        return f"❌ Limit reached ({config.MAX_HELPERS} helpers). Remove one first."
    if len(session) < 40 or " " in session:
        return "❌ That doesn't look like a Pyrogram session string."
    existing = {config.SESSION_STRING, *config.SESSION_STRINGS, *[s for _, s in await cred.list_helper_sessions()]}
    if session in existing:
        return "ℹ️ That session is already added."
    proxy = await free_proxy()
    if proxy is None and config.HELPER_REQUIRE_PROXY:
        return ("❌ No free proxy for this account. Each helper account needs its <b>own</b> proxy (same country as the "
                "account is best): add one in 🧦 Proxies first, then add the helper again.")
    try:
        helper = await _start(session, "db", proxy=proxy)
    except Exception as e:
        return f"❌ Couldn't log in with that session ({type(e).__name__}). Generate a fresh session string."
    if any(h.id == helper.id and h is not helper for h in player.helpers()):
        await helper.client.stop()
        player.remove_helper(helper)
        return "ℹ️ That Telegram account is already a helper."
    helper.db_id = await cred.add_helper_session(session, proxy)
    report = await brand(helper) if config.HELPER_BRANDING else []
    who = f"@{helper.username}" if helper.username else str(helper.id)
    via = f"via {proxy_manager.mask(proxy)}" if proxy else "⚠️ direct (no proxy)"
    return f"✅ Helper #{helper.index} ready: <code>{who}</code> · {via}\n" + "\n".join(report)


async def remove(index: int) -> str:
    target = next((h for h in player.helpers() if h.index == index), None)
    if not target:
        return "❌ No such helper."
    if target.source != "db":
        return "ℹ️ This helper comes from .env (SESSION_STRING / SESSION_STRINGS). Remove it there and restart."
    if player._load(target):
        return f"❌ Helper #{index} is serving {player._load(target)} group(s). /stop their music or wait, then try again."
    if target.db_id:
        await cred.remove_helper_session(target.db_id)
    try:
        await target.client.stop()
    except Exception:
        pass
    player.remove_helper(target)
    return f"🗑 Helper #{index} removed."


def overview() -> str:
    hs = player.helpers()
    lines = [f"🤖 <b>Helper accounts</b> ({len(hs)}/{config.MAX_HELPERS})"]
    for h in hs:
        who = f"@{h.username}" if h.username else (str(h.id) if h.id else "?")
        busy = player._load(h)
        via = "🧦 proxy" if h.proxy else "⚠️ no proxy"
        lines.append(f"{h.index}. <b>{h.name or expected_name(h.index)}</b> · <code>{who}</code> · {busy} group(s) · {via}"
                     f"{'' if h.source == 'env' else ' · panel'}")
    lines.append("\nOne helper can play in many groups at once; more helpers spread the load and avoid flood limits. "
                 "Each account keeps its own proxy for good. Profile branding runs only when you press the button.")
    return "\n".join(lines)


# ------------------------------------------------------------------ log a new account in from the bot chat
_logins: dict[int, dict] = {}  # owner id -> {"client", "phone", "hash", "proxy"}


async def _drop_login(uid: int):
    st = _logins.pop(uid, None)
    if st:
        try:
            await st["client"].disconnect()
        except Exception:
            pass


async def login_cancel(uid: int):
    await _drop_login(uid)


async def login_begin(uid: int, phone: str) -> str:
    """Step 1: send the login code. The login runs through the account's own proxy, so Telegram sees one stable IP."""
    await _drop_login(uid)
    if len(player.helpers()) >= config.MAX_HELPERS:
        return "❌ Helper limit reached."
    proxy = await free_proxy()
    if proxy is None and config.HELPER_REQUIRE_PROXY:
        return ("❌ No free proxy. Each helper account needs its <b>own</b> proxy: add one in 🧦 Proxies first.")
    phone = "+" + "".join(ch for ch in phone if ch.isdigit())
    client = Client(f"ria_login_{uid}", api_id=config.API_ID, api_hash=config.API_HASH, in_memory=True,
                    proxy=tg_proxy_dict(proxy))
    try:
        await client.connect()
        sent = await client.send_code(phone)
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        name = type(e).__name__
        if "PhoneNumberInvalid" in name:
            return "❌ That phone number is invalid. Send it with the country code, e.g. +1 555 123 4567."
        if "FloodWait" in name:
            return f"❌ Telegram says wait {getattr(e, 'value', '?')}s before asking for another code."
        return f"❌ Couldn't request the code ({name})."
    _logins[uid] = {"client": client, "phone": phone, "hash": sent.phone_code_hash, "proxy": proxy}
    return "OK"


async def login_code(uid: int, code: str) -> str:
    """Step 2: the code. Returns OK | PASSWORD | RETRY:<msg> | <final report>."""
    st = _logins.get(uid)
    if not st:
        return "❌ Login expired. Start again."
    digits = "".join(ch for ch in code if ch.isdigit())
    try:
        await st["client"].sign_in(st["phone"], st["hash"], digits)
    except Exception as e:
        name = type(e).__name__
        if "SessionPasswordNeeded" in name:
            return "PASSWORD"
        if "PhoneCodeInvalid" in name:
            return "RETRY:That code is wrong. Send it again."
        await _drop_login(uid)
        if "PhoneCodeExpired" in name:
            return "❌ The code expired. Start again."
        return f"❌ Login failed ({name})."
    return await _finish_login(uid)


async def login_password(uid: int, password: str) -> str:
    st = _logins.get(uid)
    if not st:
        return "❌ Login expired. Start again."
    try:
        await st["client"].check_password(password)
    except Exception as e:
        if "PasswordHashInvalid" in type(e).__name__:
            return "RETRY:Wrong password. Send it again."
        await _drop_login(uid)
        return f"❌ Login failed ({type(e).__name__})."
    return await _finish_login(uid)


async def _finish_login(uid: int) -> str:
    st = _logins[uid]
    try:
        session = await st["client"].export_session_string()
    finally:
        await _drop_login(uid)
    await asyncio.sleep(3)
    return await add_from_owner(session)
