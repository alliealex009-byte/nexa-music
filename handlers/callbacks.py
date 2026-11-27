import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery

from database import groups as groups_db
from database import playlists as pl_db
from handlers.lyrics import send_lyrics
from handlers.play import SEARCH_CACHE, controls_for, enqueue_tracks, now_playing_text, queued_text
from handlers.playlists import load_into_queue, playlist_text
from handlers.premium import premium_text
from handlers.queue import queue_text
from handlers.start import show_home
from keyboards import inline as kb
from keyboards import settings as skb
from services import helptext, player, queue_manager, ui
from utils.permissions import can_control_uid, can_play_uid, is_admin

log = logging.getLogger("callbacks")


async def _edit(q: CallbackQuery, text: str, rows=None):
    await ui.edit_cb(q, text, rows)


@Client.on_callback_query(filters.regex(r"^noop$"))
async def noop_cb(client, q):
    await q.answer()


# ------------------------------------------------------------------ main menu
@Client.on_callback_query(filters.regex(r"^menu:"))
async def menu_cb(client: Client, q: CallbackQuery):
    action = q.data.split(":")[1]
    chat_id = q.message.chat.id
    if action == "home":
        await show_home(q)
    elif action == "play":
        await _edit(q, "🎵 <b>Play music</b>\nIn a group use:\n<code>/play song name or link</code>\n"
                       "Also: /mix · /vplay · /fplay · /lyrics", kb.play_menu())
    elif action == "search":
        await _edit(q, "🔎 <b>Search</b>\nIn a group use:\n<code>/search song name</code>", kb.back_button())
    elif action == "queue":
        await _edit(q, queue_text(chat_id), kb.back_button())
    elif action == "playlists":
        items = await pl_db.list_for(q.from_user.id)
        text = "🎧 <b>Your playlists</b>" if items else "No playlists yet. Use <code>/createplaylist name</code>."
        await _edit(q, text, kb.playlists_panel(items))
    elif action == "settings":
        if q.message.chat.type == ChatType.PRIVATE:
            await _edit(q, "⚙️ Use /settings inside a group.", kb.back_button())
        elif not await is_admin(client, chat_id, q.from_user.id):
            return await q.answer("Admins only.", show_alert=True)
        else:
            text, rows = skb.page("home", await groups_db.get_settings(chat_id))
            await _edit(q, text, rows)
    elif action == "premium":
        await _edit(q, await premium_text(q.from_user.id), kb.back_button())
    await q.answer()


@Client.on_callback_query(filters.regex(r"^help:"))
async def help_cb(client, q):
    page = q.data.split(":")[1]
    if page == "home":
        await _edit(q, helptext.hub_text(), kb.help_hub())
    elif page in helptext.PAGES:
        await _edit(q, helptext.PAGES[page], kb.help_page(page))
    await q.answer()


# ------------------------------------------------------------------ player buttons
@Client.on_callback_query(filters.regex(r"^ctl:"))
async def control_cb(client: Client, q: CallbackQuery):
    chat_id = q.message.chat.id
    action = q.data.split(":")[1]
    settings = await groups_db.get_settings(chat_id)
    msg_id = q.message.id

    if action == "queue":
        return await q.answer(_short(queue_text(chat_id)), show_alert=True)
    if action == "lyrics":
        cur = queue_manager.current(chat_id)
        if not cur:
            return await q.answer("Nothing is playing.", show_alert=True)
        await q.answer("Fetching lyrics…")
        return await send_lyrics(chat_id, cur.title)
    if action in ("more", "back"):
        await ui.edit_markup(chat_id, msg_id, controls_for(chat_id, more=action == "more", settings=settings))
        return await q.answer()

    if not await can_control_uid(client, chat_id, q.from_user.id, settings):
        return await q.answer("Only admins or authorized users can do this.", show_alert=True)
    cur = queue_manager.current(chat_id)
    if cur is None and action != "stop":
        return await q.answer("Nothing is playing.", show_alert=True)
    try:
        if action == "pause":
            await player.pause(chat_id)
            await q.answer("Paused")
        elif action == "resume":
            await player.resume(chat_id)
            await q.answer("Resumed")
        elif action == "skip":
            nxt = await player.skip(chat_id)
            await q.answer("Skipped" if nxt else "Queue finished")
        elif action == "stop":
            await player.stop(chat_id)
            await q.answer("Stopped")
        elif action in ("seekb", "seekf"):
            new = await player.seek(chat_id, -10 if action == "seekb" else 10)
            await q.answer("Can't seek here" if new is None else f"At {new // 60}:{new % 60:02d}")
        elif action in ("mute", "unmute"):
            await (player.mute if action == "mute" else player.unmute)(chat_id)
            await ui.edit_markup(chat_id, msg_id, controls_for(chat_id, more=True, settings=settings))
            await q.answer("Muted" if action == "mute" else "Unmuted")
        elif action == "loop":
            nxt_mode = {"off": "track", "track": "queue", "queue": "off"}[queue_manager.loop_mode(chat_id)]
            queue_manager.set_loop(chat_id, nxt_mode)
            await ui.edit_markup(chat_id, msg_id, controls_for(chat_id, more=True, settings=settings))
            await q.answer(f"Loop: {nxt_mode}")
        elif action == "shuffle":
            n = queue_manager.shuffle(chat_id)
            await q.answer(f"Shuffled {n} tracks" if n else "The queue is empty")
        elif action == "autoplay":
            await groups_db.set_setting(chat_id, "autoplay", not settings["autoplay"])
            settings = await groups_db.get_settings(chat_id)
            await ui.edit_markup(chat_id, msg_id, controls_for(chat_id, more=True, settings=settings))
            await q.answer("Autoplay " + ("on" if settings["autoplay"] else "off"))
        else:
            await q.answer()
    except Exception:
        log.exception("control button failed")
        await q.answer("That didn't work.", show_alert=True)


def _short(text: str) -> str:
    import re

    plain = re.sub(r"<[^>]+>", "", text)
    return plain[:190]


# ------------------------------------------------------------------ search picks
@Client.on_callback_query(filters.regex(r"^(v?pick):"))
async def pick_cb(client: Client, q: CallbackQuery):
    kind, idx = q.data.split(":")
    chat_id = q.message.chat.id
    cached = SEARCH_CACHE.get(chat_id)
    settings = await groups_db.get_settings(chat_id)
    if not await can_play_uid(client, chat_id, q.from_user.id, settings):
        return await q.answer("Playing is restricted to admins here.", show_alert=True)
    if not cached or int(idx) >= len(cached[0]):
        return await q.answer("Results expired, search again.", show_alert=True)
    track = cached[0][int(idx)]
    await q.answer("Adding…")
    err = await player.ensure_assistant(chat_id)
    if err:
        return await _edit(q, f"❌ {err}")
    status, pos, _ = await enqueue_tracks(chat_id, [track], q.from_user.id, q.from_user.first_name,
                                          video=kind == "vpick")
    lang = settings["language"]
    if status == "playing":
        text = now_playing_text(track, lang)
    elif status == "queued":
        text = queued_text(track, pos, 0, lang)
    elif status == "full":
        text = "⚠️ The queue is full."
    else:
        text = "❌ Couldn't start playback. Is a voice chat active?"
    await _edit(q, text, controls_for(chat_id, settings=settings) if status in ("playing", "queued") else None)


# ------------------------------------------------------------------ settings sub-menus
@Client.on_callback_query(filters.regex(r"^st:"))
async def settings_cb(client: Client, q: CallbackQuery):
    chat_id = q.message.chat.id
    if not await is_admin(client, chat_id, q.from_user.id):
        return await q.answer("Admins only.", show_alert=True)
    parts = q.data.split(":")
    action = parts[1]
    try:
        if action == "tog":
            if parts[2] not in groups_db.BOOL_KEYS:
                raise KeyError(parts[2])
            s = await groups_db.get_settings(chat_id)
            await groups_db.set_setting(chat_id, parts[2], not s[parts[2]])
            page = "home"
        elif action == "set":
            value = int(parts[3]) if parts[2] == "auto_delete" else parts[3]
            await groups_db.set_setting(chat_id, parts[2], value)
            page = "home" if parts[2] != "language" else "language"
        else:
            page = parts[2] if action == "open" else "home"
    except (ValueError, KeyError):
        return await q.answer("Invalid option.", show_alert=True)
    s = await groups_db.get_settings(chat_id)
    text, rows = skb.page(page, s)
    await _edit(q, text, rows)
    await q.answer("Updated" if action in ("tog", "set") else None)


# ------------------------------------------------------------------ playlists
@Client.on_callback_query(filters.regex(r"^pl:"))
async def playlist_cb(client: Client, q: CallbackQuery):
    _, action, pid = q.data.split(":")
    pid = int(pid)
    if await pl_db.owner_of(pid) != q.from_user.id:
        return await q.answer("Not your playlist.", show_alert=True)
    if action == "open":
        name = next((n for i, n in await pl_db.list_for(q.from_user.id) if i == pid), "Playlist")
        await _edit(q, await playlist_text(pid, name), kb.playlist_actions(pid))
    elif action == "play":
        if q.message.chat.type == ChatType.PRIVATE:
            return await q.answer("Play playlists from inside a group.", show_alert=True)
        n, err = await load_into_queue(client, q.message.chat.id, pid, q.from_user)
        return await q.answer(err or f"Queued {n} tracks", show_alert=bool(err))
    elif action == "del":
        await pl_db.delete(pid)
        items = await pl_db.list_for(q.from_user.id)
        await _edit(q, "🗑 Deleted.", kb.playlists_panel(items))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^close$"))
async def close_cb(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        await q.answer()
