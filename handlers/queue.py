from pyrogram import Client, filters

from database import groups as groups_db
from services import queue_manager, ui
from utils import guards
from utils.guards import group_cmd, respond, with_silent
from utils.permissions import can_control
from utils.text import esc, fmt_duration


def queue_text(chat_id: int) -> str:
    cur = queue_manager.current(chat_id)
    ups = queue_manager.upcoming(chat_id)
    if not cur and not ups:
        return "📋 The queue is empty."
    lines = []
    if cur:
        lines.append(f"▶️ <b>Now playing</b>\n{esc(cur.title)} ({fmt_duration(cur.duration)})\n")
    if ups:
        lines.append("<b>Up next:</b>")
        for i, t in enumerate(ups[:10], 1):
            lines.append(f"{i}. {esc(t.title)} ({fmt_duration(t.duration)})")
        if len(ups) > 10:
            lines.append(f"…and {len(ups) - 10} more")
    mode = queue_manager.loop_mode(chat_id)
    if mode != "off":
        lines.append(f"\n🔁 Loop: {mode}")
    return "\n".join(lines)


async def _allowed(client, message, ctx) -> bool:
    if await can_control(client, message, ctx.settings):
        return True
    await ui.reply(message, ctx.t("admins_only"))
    return False


@Client.on_message(filters.command(["queue", "q"]) & filters.group)
@group_cmd
async def queue_cmd(client, message, ctx):
    await ui.reply(message, queue_text(message.chat.id))


@Client.on_message(filters.command(with_silent(guards.REMOVE)) & filters.group)
@group_cmd
async def remove_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    try:
        idx = int(message.command[1])
    except (IndexError, ValueError):
        return await ui.reply(message, "Usage: <code>/remove 2</code> (position in /queue)")
    track = queue_manager.remove_at(message.chat.id, idx)
    if not track:
        return await ui.reply(message, "❌ No track at that position.")
    await respond(message, ctx, f"🗑 Removed <b>{esc(track.title)}</b>", success=True)


@Client.on_message(filters.command(with_silent(guards.CLEAR)) & filters.group)
@group_cmd
async def clear_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    n = queue_manager.clear_upcoming(message.chat.id)
    await respond(message, ctx, f"🧹 Cleared {n} queued tracks.", success=True)


@Client.on_message(filters.command(with_silent(guards.SHUFFLE)) & filters.group)
@group_cmd
async def shuffle_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    n = queue_manager.shuffle(message.chat.id)
    if not n:
        return await ui.reply(message, "The queue is empty.")
    await respond(message, ctx, f"🔀 Shuffled {n} tracks.", success=True)


@Client.on_message(filters.command(with_silent(guards.LOOP)) & filters.group)
@group_cmd
async def loop_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    chat_id = message.chat.id
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    modes = {"off": "off", "0": "off", "track": "track", "one": "track", "1": "track", "queue": "queue", "all": "queue"}
    if arg in modes:
        mode = modes[arg]
    else:  # no argument: cycle
        mode = {"off": "track", "track": "queue", "queue": "off"}[queue_manager.loop_mode(chat_id)]
    queue_manager.set_loop(chat_id, mode)
    await respond(message, ctx, f"🔁 Loop: <b>{mode}</b>", success=True)


@Client.on_message(filters.command(with_silent(guards.AUTOPLAY)) & filters.group)
@group_cmd
async def autoplay_cmd(client, message, ctx):
    if not await _allowed(client, message, ctx):
        return
    cur = ctx.settings["autoplay"]
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    new = True if arg in ("on", "1", "yes") else False if arg in ("off", "0", "no") else not cur
    await groups_db.set_setting(message.chat.id, "autoplay", new)
    await respond(message, ctx, f"♾ Autoplay: <b>{'on' if new else 'off'}</b>", success=True)


@Client.on_message(filters.command("reload") & filters.group)
@group_cmd
async def reload_cmd(client, message, ctx):
    groups_db.invalidate(message.chat.id)
    await respond(message, ctx, "🔄 Settings reloaded.", success=True)
