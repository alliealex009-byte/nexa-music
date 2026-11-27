"""Shared plumbing for group commands: settings, language, silent mode, command deletion."""
import functools
import logging
from dataclasses import dataclass

from pyrogram.enums import ChatType

from database import groups as groups_db
from services import i18n, ui

log = logging.getLogger("guards")

# Base command names (without the s prefix). Each also exists as an "s" variant = silent.
PLAY = ["play", "p"]
VPLAY = ["vplay", "vp"]
FPLAY = ["fplay"]
FVPLAY = ["fvplay"]
MIX = ["mix"]
SKIP = ["skip", "next"]
PAUSE = ["pause"]
RESUME = ["resume"]
STOP = ["stop", "end"]
SEEK = ["seek"]
MUTE = ["mute"]
UNMUTE = ["unmute"]
LOOP = ["loop"]
SHUFFLE = ["shuffle"]
CLEAR = ["clear"]
REMOVE = ["remove"]
VOLUME = ["volume"]
AUTOPLAY = ["autoplay"]
SEARCH = ["search"]
LYRICS = ["lyrics"]

SILENCEABLE = {n for group in (PLAY, VPLAY, FPLAY, FVPLAY, MIX, SKIP, PAUSE, RESUME, STOP, SEEK, MUTE, UNMUTE,
                               LOOP, SHUFFLE, CLEAR, REMOVE, VOLUME, AUTOPLAY, SEARCH) for n in group}


def with_silent(names: list[str]) -> list[str]:
    return names + ["s" + n for n in names]


def is_silent(message, settings: dict) -> bool:
    if settings.get("silent"):
        return True
    cmd = (message.command[0] if message.command else "").lower()
    return cmd.startswith("s") and cmd[1:] in SILENCEABLE


@dataclass
class Ctx:
    settings: dict
    lang: str
    silent: bool

    def t(self, key: str, **kw) -> str:
        return i18n.t(self.lang, key, **kw)


def query_of(message) -> str:
    if message.command and len(message.command) > 1:
        return message.text.split(None, 1)[1].strip()
    r = message.reply_to_message
    if r and (r.text or r.caption):
        return (r.text or r.caption).strip()
    return ""


def group_cmd(func):
    """Wrap a group command handler: builds Ctx, reports crashes, deletes the command if configured."""

    @functools.wraps(func)
    async def wrapper(client, message):
        if not message.chat or message.chat.type == ChatType.PRIVATE:
            return
        settings = await groups_db.get_settings(message.chat.id)
        ctx = Ctx(settings, settings["language"], is_silent(message, settings))
        try:
            await func(client, message, ctx)
        except Exception:
            log.exception("command failed: %s", message.text)
            try:
                await ui.reply(message, "⚠️ Something went wrong. Please try again.")
            except Exception:
                pass
        finally:
            if settings["delete_commands"]:
                try:
                    await message.delete()
                except Exception:
                    pass

    return wrapper


async def respond(message, ctx: Ctx, text: str, rows=None, *, success: bool = False):
    """Send a reply; success messages are skipped in silent mode (errors always show)."""
    if success and ctx.silent:
        return None
    return await ui.reply(message, text, rows)


# ------------------------------------------------------------------ owner-only commands
def owner_cmd(func=None, *, private_only: bool = False):
    """Owner-only command. Non-owners get a hint with their own Telegram ID in private chat (so a wrong
    OWNER_ID in .env is easy to spot) and are ignored in groups. `private_only` is for commands that
    handle secrets."""

    def decorate(fn):
        @functools.wraps(fn)
        async def wrapper(client, message):
            import config

            uid = message.from_user.id if message.from_user else None
            is_private = message.chat.type == ChatType.PRIVATE
            if uid is None or uid != config.OWNER_ID:
                if is_private:
                    await ui.reply(
                        message,
                        "🚫 <b>Owner only.</b>\n"
                        f"Your Telegram ID is <code>{uid}</code>. If you are the owner, put "
                        f"<code>OWNER_ID={uid}</code> in your .env file and restart the bot.",
                    )
                return
            if private_only and not is_private:
                return await ui.reply(message, "🔒 Use this command in a private chat with me.")
            try:
                await fn(client, message)
            except Exception:
                log.exception("owner command failed: %s", (message.text or "")[:40])
                await ui.reply(message, "⚠️ That failed — see the bot log for details.")

        return wrapper

    return decorate(func) if func else decorate
