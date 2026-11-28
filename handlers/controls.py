from pyrogram import Client, filters

from services import player, queue_manager, ui
from utils import guards
from utils.guards import group_cmd, respond, with_silent
from utils.permissions import can_control
from utils.text import fmt_clock


async def _allowed(client, message, ctx) -> bool:
    if await can_control(client, message, ctx.settings):
        return True
    await ui.reply(message, ctx.t("admins_only"))
    return False


async def _playing(message, ctx) -> bool:
    if queue_manager.current(message.chat.id) is None:
        await ui.reply(message, ctx.t("nothing_playing"))
        return False
    return True


@Client.on_message(filters.command(with_silent(guards.SKIP)) & filters.group)
@group_cmd
async def skip_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    await player.skip(message.chat.id, announce=not ctx.silent)


@Client.on_message(filters.command(with_silent(guards.PAUSE)) & filters.group)
@group_cmd
async def pause_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    if not await player.pause(message.chat.id):
        return await ui.reply(message, "❌ Couldn't pause — the stream isn't responding. Try /skip or /play again.")
    await respond(message, ctx, ctx.t("paused"), success=True)


@Client.on_message(filters.command(with_silent(guards.RESUME)) & filters.group)
@group_cmd
async def resume_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    if not await player.resume(message.chat.id):
        return await ui.reply(message, "❌ Couldn't resume — the stream isn't responding. Try /skip or /play again.")
    await respond(message, ctx, ctx.t("resumed"), success=True)


@Client.on_message(filters.command(with_silent(guards.STOP)) & filters.group)
@group_cmd
async def stop_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    await player.stop(message.chat.id)
    await respond(message, ctx, ctx.t("stopped"), success=True)


@Client.on_message(filters.command(with_silent(guards.MUTE)) & filters.group)
@group_cmd
async def mute_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    if not await player.mute(message.chat.id):
        return await ui.reply(message, "❌ Couldn't mute — the stream isn't responding. Try /skip or /play again.")
    await respond(message, ctx, ctx.t("muted"), success=True)


@Client.on_message(filters.command(with_silent(guards.UNMUTE)) & filters.group)
@group_cmd
async def unmute_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    if not await player.unmute(message.chat.id):
        return await ui.reply(message, "❌ Couldn't unmute — the stream isn't responding. Try /skip or /play again.")
    await respond(message, ctx, ctx.t("unmuted"), success=True)


def parse_seek(arg: str) -> int | None:
    arg = arg.strip().lower().rstrip("s")
    try:
        return int(arg)
    except ValueError:
        return None


@Client.on_message(filters.command(with_silent(guards.SEEK)) & filters.group)
@group_cmd
async def seek_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx) or not await _playing(message, ctx):
        return
    delta = parse_seek(message.command[1]) if len(message.command) > 1 else None
    if not delta:
        return await ui.reply(message, "Usage: <code>/seek 30</code> (forward) or <code>/seek -30</code> (back)")
    new = await player.seek(message.chat.id, delta)
    if new is None:
        return await ui.reply(message, "❌ Can't seek there (live streams and the end of a track are not seekable).")
    await respond(message, ctx, f"{'⏩' if delta > 0 else '⏪'} Now at {fmt_clock(new)}", success=True)


@Client.on_message(filters.command(with_silent(guards.VOLUME)) & filters.group)
@group_cmd
async def volume_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    from database import groups as groups_db

    try:
        vol = int(message.command[1])
        if not 1 <= vol <= 200:
            raise ValueError
    except (IndexError, ValueError):
        return await ui.reply(message, "Usage: <code>/volume 1-200</code>")
    await groups_db.set_setting(message.chat.id, "volume", vol)
    if queue_manager.current(message.chat.id):
        await player.set_volume(message.chat.id, vol)
    await respond(message, ctx, f"🔊 Volume: {vol}%", success=True)
