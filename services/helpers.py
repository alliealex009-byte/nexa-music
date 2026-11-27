"""Helper (assistant) accounts: start them, brand them, add/remove them at runtime.

A helper is a normal Telegram user account logged in with a session string. It joins the voice chats and streams the
audio. One helper can stream in many groups at the same time; with more helpers the groups are spread over them.
"""
import logging
import os

from pyrogram import Client
from pytgcalls import PyTgCalls

import config
from database import credentials as cred
from services import player

log = logging.getLogger("helpers")


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
    if photo:
        try:
            old = [p.file_id async for p in c.get_chat_photos("me")]
            if old:
                await c.delete_profile_photos(old)
                report.append(f"🗑 removed {len(old)} old photo(s)")
        except Exception as e:
            report.append(f"⚠️ couldn't remove old photos ({type(e).__name__})")
        if os.path.exists(config.HELPER_DP):
            try:
                await c.set_profile_photo(photo=config.HELPER_DP)
                report.append("✅ new profile photo")
            except Exception as e:
                report.append(f"⚠️ couldn't set the photo ({type(e).__name__})")
    try:
        await player.helper_me(helper)
    except Exception:
        pass
    return report


async def _start(session: str, source: str, db_id: int | None = None) -> player.Helper:
    n = len(player.helpers()) + 1
    client = Client(f"ria_helper_{n}", api_id=config.API_ID, api_hash=config.API_HASH, session_string=session,
                    in_memory=True)
    calls = PyTgCalls(client)
    await client.start()
    try:
        await calls.start()
    except Exception:
        await client.stop()
        raise
    helper = player.add_helper(client, calls, source, db_id)
    await player.helper_me(helper)
    return helper


async def start_extra() -> list[str]:
    """Start helpers #2.. from SESSION_STRINGS and the database. Returns problems (for the owner)."""
    problems = []
    seen = {config.SESSION_STRING}
    jobs = [(s, "env", None) for s in config.SESSION_STRINGS] + [(s, "db", rid) for rid, s in await cred.list_helper_sessions()]
    for session, source, db_id in jobs:
        if session in seen:
            continue
        seen.add(session)
        if len(player.helpers()) >= config.MAX_HELPERS:
            problems.append(f"Helper limit ({config.MAX_HELPERS}) reached; skipped one session.")
            break
        try:
            await _start(session, source, db_id)
        except Exception as e:
            log.warning("helper session failed to start: %s", type(e).__name__)
            problems.append(f"A helper session failed to start ({type(e).__name__}); check or remove it.")
    return problems


async def brand_all(force: bool = False) -> list[str]:
    """At startup: fix names (and the first-time photo) of helpers that aren't branded yet."""
    out = []
    if not config.HELPER_BRANDING and not force:
        return out
    for h in player.helpers():
        if force or h.name != expected_name(h.index):
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
    try:
        helper = await _start(session, "db")
    except Exception as e:
        return f"❌ Couldn't log in with that session ({type(e).__name__}). Generate a fresh session string."
    if any(h.id == helper.id and h is not helper for h in player.helpers()):
        await helper.client.stop()
        player.remove_helper(helper)
        return "ℹ️ That Telegram account is already a helper."
    helper.db_id = await cred.add_helper_session(session)
    report = await brand(helper) if config.HELPER_BRANDING else []
    who = f"@{helper.username}" if helper.username else str(helper.id)
    return f"✅ Helper #{helper.index} ready: <code>{who}</code>\n" + "\n".join(report)


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
        lines.append(f"{h.index}. <b>{h.name or expected_name(h.index)}</b> · <code>{who}</code> · {busy} group(s)"
                     f"{'' if h.source == 'env' else ' · panel'}")
    lines.append("\nOne helper can play in many groups at once; more helpers spread the load and avoid flood limits. "
                 "Names, bio and photo are set automatically.")
    return "\n".join(lines)
