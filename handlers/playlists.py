from pyrogram import Client, filters

import config
from database import playlists as pl_db
from database import subscriptions as subs_db
from keyboards.inline import playlists_panel
from services import music_search, player, queue_manager, ui
from services.models import Track
from utils.text import esc, fmt_duration


async def _limit(user_id: int) -> int:
    return config.PREMIUM_PLAYLIST_LIMIT if await subs_db.is_premium(user_id) else config.FREE_PLAYLIST_LIMIT


def split_args(message) -> tuple[str, str]:
    """'name | rest' -> (name, rest); without a bar the whole text is the name."""
    parts = message.text.split(None, 1)
    raw = parts[1].strip() if len(parts) > 1 else ""
    if "|" in raw:
        name, rest = raw.split("|", 1)
        return name.strip(), rest.strip()
    return raw, ""


@Client.on_message(filters.command(["myplaylists", "playlists"]))
async def myplaylists_cmd(client, message):
    items = await pl_db.list_with_counts(message.from_user.id)
    if not items:
        return await ui.reply(message, "You have no playlists yet.\nCreate one: <code>/createplaylist name</code>")
    body = "\n".join(f"• <b>{esc(n)}</b> — {c} tracks" for _, n, c in items)
    await ui.reply(message, f"🎧 <b>Your playlists</b>\n{body}", playlists_panel([(i, n) for i, n, _ in items]))


@Client.on_message(filters.command(["createplaylist", "newplaylist"]))
async def create_cmd(client, message):
    name, _ = split_args(message)
    if not name:
        return await ui.reply(message, "Usage: <code>/createplaylist name</code>")
    uid = message.from_user.id
    if await pl_db.count(uid) >= await _limit(uid):
        return await ui.reply(message, "⚠️ Playlist limit reached. Upgrade with /premium.")
    ok = await pl_db.find(uid, name[:40]) is None and await pl_db.create(uid, name[:40])
    await ui.reply(message, f"✅ Created <b>{esc(name[:40])}</b>." if ok else "❌ A playlist with that name already exists.")


@Client.on_message(filters.command("deleteplaylist"))
async def delete_cmd(client, message):
    name, _ = split_args(message)
    found = await pl_db.find(message.from_user.id, name) if name else None
    if not found:
        return await ui.reply(message, "❌ Playlist not found. Usage: <code>/deleteplaylist name</code>")
    await pl_db.delete(found[0])
    await ui.reply(message, f"🗑 Deleted <b>{esc(found[1])}</b>.")


@Client.on_message(filters.command(["addtoplaylist", "addtrack"]))
async def add_cmd(client, message):
    name, query = split_args(message)
    uid = message.from_user.id
    found = await pl_db.find(uid, name) if name else None
    if not found:
        return await ui.reply(message, "Usage: <code>/addtoplaylist playlist | song or link</code>\n"
                                       "(inside a group, leave the song out to add the current one)")
    if query:
        track = await music_search.resolve(query)
    else:
        track = queue_manager.current(message.chat.id)
        if track and not track.url:
            track = None
    if not track:
        return await ui.reply(message, "❌ No song found to add.")
    await pl_db.add_track(found[0], track.title, track.url, track.duration)
    await ui.reply(message, f"✅ Added <b>{esc(track.title)}</b> to <b>{esc(found[1])}</b>.")


@Client.on_message(filters.command("removefromplaylist"))
async def remove_cmd(client, message):
    name, rest = split_args(message)
    found = await pl_db.find(message.from_user.id, name) if name else None
    if not found or not rest.isdigit():
        return await ui.reply(message, "Usage: <code>/removefromplaylist playlist | number</code>")
    removed = await pl_db.remove_track_at(found[0], int(rest))
    if not removed:
        return await ui.reply(message, "❌ No track with that number.")
    await ui.reply(message, f"🗑 Removed <b>{esc(removed[0])}</b>.")


async def playlist_text(pid: int, name: str) -> str:
    tracks = await pl_db.tracks(pid)
    body = "\n".join(f"{i}. {esc(t[0])} ({fmt_duration(t[2])})" for i, t in enumerate(tracks[:40], 1)) or "Empty playlist."
    more = f"\n…and {len(tracks) - 40} more" if len(tracks) > 40 else ""
    return f"🎧 <b>{esc(name)}</b> — {len(tracks)} tracks\n{body}{more}"


@Client.on_message(filters.command("playlistinfo"))
async def info_cmd(client, message):
    name, _ = split_args(message)
    found = await pl_db.find(message.from_user.id, name) if name else None
    if not found:
        return await ui.reply(message, "❌ Playlist not found. Usage: <code>/playlistinfo name</code>")
    await ui.reply(message, await playlist_text(*found))


async def load_into_queue(client, chat_id: int, pid: int, user) -> tuple[int, str | None]:
    """Queue every track of a playlist. Returns (queued, error text or None)."""
    err = await player.ensure_assistant(chat_id)
    if err:
        return 0, err
    count = 0
    for title, url, duration in await pl_db.tracks(pid):
        t = Track(title=title, url=url, duration=duration, source=Track.source_for(url),
                  requested_by=user.id, requested_name=user.first_name)
        status, _ = await player.play_or_queue(chat_id, t)
        if status == "error":
            return count, "Couldn't start playback (is a voice chat active?)."
        if status == "full":
            break
        count += 1
    return count, None


@Client.on_message(filters.command("playplaylist") & filters.group)
async def play_cmd(client, message):
    name, _ = split_args(message)
    found = await pl_db.find(message.from_user.id, name) if name else None
    if not found:
        return await ui.reply(message, "❌ Playlist not found. Usage: <code>/playplaylist name</code>")
    n, err = await load_into_queue(client, message.chat.id, found[0], message.from_user)
    await ui.reply(message, f"❌ {esc(err)}" if err else f"✅ Queued {n} tracks from <b>{esc(found[1])}</b>.")
