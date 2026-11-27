import asyncio
import logging
import os

from pyrogram import Client, filters
from pyrogram.types import Message

import config
from database import groups as groups_db
from keyboards.inline import player_controls, search_results
from services import logchat, music_search, nowplaying, player, queue_manager, ui
from services.models import Track
from utils import guards
from utils.guards import Ctx, group_cmd, query_of, with_silent
from utils.permissions import can_play
from utils.text import esc, fmt_duration

log = logging.getLogger("play")

# chat_id -> (tracks, video) from the last /search, used by the pick callbacks
SEARCH_CACHE: dict[int, tuple[list[Track], bool]] = {}


# ------------------------------------------------------------------ cards
def now_playing_text(track: Track, lang: str = "en") -> str:
    from services.i18n import t

    title = esc(track.title)
    name = f'<a href="{esc(track.url)}">{title}</a>' if track.url.startswith("http") else title
    extra = " • 🎬 Video" if track.video else ""
    who = esc(track.requested_name or "—")
    return (
        f"{ui.em('play', '▶️')} <b>{t(lang, 'now_playing')}</b>\n{name}\n"
        f"⏱ {fmt_duration(track.duration)} • 👤 {who}{extra}"
    )


def queued_text(track: Track, pos: int, more: int, lang: str = "en") -> str:
    from services.i18n import t

    extra = f"\n➕ +{more} more tracks queued" if more else ""
    return (
        f"{ui.em('queue', '📋')} <b>{t(lang, 'queued', pos=pos)}</b>\n{esc(track.title)}\n"
        f"⏱ {fmt_duration(track.duration)}{extra}"
    )


def controls_for(chat_id: int, more: bool = False, settings: dict | None = None):
    return nowplaying.controls(chat_id, settings or {}, more)


def _fail_text(ctx_or_lang, chat_id: int) -> str:
    lang = ctx_or_lang.lang if isinstance(ctx_or_lang, Ctx) else ctx_or_lang
    from services.i18n import t

    reason = player.last_error.get(chat_id)
    key = {"no_vc": "no_vc", "blocked": "yt_blocked", "js": "yt_js", "unavailable": "unavailable"}.get(reason, "play_failed")
    return t(lang, key)


# ------------------------------------------------------------------ hooks used by the player
async def _on_now_playing(chat_id: int, track: Track):
    settings = await groups_db.get_settings(chat_id)
    if settings["silent"]:
        return
    await nowplaying.post(chat_id, track, settings)
    await logchat.event(f"▶️ <b>{esc(track.title)}</b> in <code>{chat_id}</code>")


async def _on_notice(chat_id: int, key: str):
    settings = await groups_db.get_settings(chat_id)
    from services.i18n import t

    if key.startswith("skip_failed:"):
        return await ui.send(chat_id, f"⚠️ Couldn't play <b>{esc(key.split(':', 1)[1])}</b>, skipping.")
    if settings["silent"] and key != "idle_stopped":
        return
    await ui.send(chat_id, t(settings["language"], key))


async def _on_state(chat_id: int):
    await nowplaying.refresh(chat_id)


async def _on_ended(chat_id: int):
    card = nowplaying.cards.get(chat_id)
    final = f"⏹ <b>Playback ended</b>\n{esc(card.track.title)}" if card else None
    await nowplaying.stop_live(chat_id, final=final)


player.hooks["state"] = _on_state
player.hooks["ended"] = _on_ended
player.hooks["now_playing"] = _on_now_playing
player.hooks["notice"] = _on_notice


# ------------------------------------------------------------------ helpers
def _requester(message: Message) -> tuple[int, str]:
    if message.from_user:
        return message.from_user.id, message.from_user.first_name or "User"
    return 0, "Anonymous"


def _media_of(reply: Message | None):
    if not reply:
        return None
    if reply.audio or reply.voice or reply.video or reply.video_note:
        return reply.audio or reply.voice or reply.video or reply.video_note
    doc = reply.document
    if doc and (doc.mime_type or "").startswith(("audio/", "video/")):
        return doc
    return None


async def _telegram_track(client: Client, reply: Message, video: bool) -> Track | str:
    media = _media_of(reply)
    size_mb = (getattr(media, "file_size", 0) or 0) / 2**20
    if size_mb > config.MAX_TG_FILE_MB:
        return f"❌ That file is {size_mb:.0f} MB; the limit is {config.MAX_TG_FILE_MB} MB."
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    path = await client.download_media(reply, file_name=config.CACHE_DIR + "/")
    if not path:
        return "❌ Couldn't download that file."
    title = getattr(media, "title", None) or getattr(media, "file_name", None) or "Telegram file"
    is_video = bool(reply.video or reply.video_note or (getattr(media, "mime_type", "") or "").startswith("video/"))
    return Track(title=title, url="", duration=int(getattr(media, "duration", 0) or 0), source="file",
                 stream_url=path, video=video and is_video)


async def _mix_tracks(query: str) -> list[Track]:
    seeds = await music_search.resolve_many(query, 1)
    if not seeds:
        return []
    seed = seeds[0]
    if seed.source == "query":  # link from a platform we can't stream: turn it into a real track first
        real = await music_search.materialize(seed)
        seed = real or seed
    related = await music_search.related(seed, max(config.MIX_SIZE - 1, 1))
    return [seed] + related


async def enqueue_tracks(chat_id: int, tracks: list[Track], user_id: int, user_name: str, *,
                         video: bool = False, force: bool = False) -> tuple[str, int, int]:
    """Returns (status, position, extra_tracks_queued)."""
    for t in tracks:
        t.requested_by, t.requested_name = user_id, user_name
        t.video = video or t.video
    if force:
        status, pos = await player.play_now(chat_id, tracks)
        return status, pos, max(len(tracks) - 1, 0) if status != "error" else 0
    status, pos = await player.play_or_queue(chat_id, tracks[0])
    extra = 0
    if status in ("playing", "queued"):
        for t in tracks[1:]:
            if queue_manager.add(chat_id, t) is None:
                break
            extra += 1
    return status, pos, extra


async def _finish(message: Message, ctx: Ctx, progress: int | None, status: str, pos: int, extra: int,
                  first: Track):
    chat_id = message.chat.id
    if status == "error":
        text = _fail_text(ctx, chat_id)
        return await _edit_or_send(message, progress, text)
    if status == "full":
        return await _edit_or_send(message, progress, ctx.t("queue_full"))
    if ctx.silent:  # progress and errors stay visible; the final success message is hidden
        if progress:
            await ui.delete(chat_id, progress)
        return
    if status == "playing":
        if progress:
            await ui.delete(chat_id, progress)
        await nowplaying.post(chat_id, queue_manager.current(chat_id) or first, ctx.settings)
        if extra:
            await ui.send(chat_id, f"➕ +{extra} more tracks queued")
    else:
        await _edit_or_send(message, progress, queued_text(first, pos, extra, ctx.lang),
                            controls_for(chat_id, settings=ctx.settings))
    await logchat.event(f"🎵 <b>{esc(first.title)}</b> requested in <code>{chat_id}</code>")


async def _edit_or_send(message: Message, progress: int | None, text: str, rows=None):
    if progress:
        await ui.edit(message.chat.id, progress, text, rows)
    else:
        await ui.reply(message, text, rows)


# ------------------------------------------------------------------ the play family
async def do_play(client: Client, message: Message, ctx: Ctx, *, video=False, force=False, mix=False):
    chat_id = message.chat.id
    if video and not config.ENABLE_VPLAY:
        return await ui.reply(message, "🎬 Video playback is turned off on this bot.")
    if not await can_play(client, message, ctx.settings):
        return await ui.reply(message, ctx.t("play_restricted"))

    reply = message.reply_to_message
    media = _media_of(reply)
    query = "" if media and len(message.command) == 1 else query_of(message)
    if not query and not media:
        return await ui.reply(message, ctx.t("usage_play"))

    await groups_db.add_group(chat_id, message.chat.title or "")
    progress = await ui.reply(message, ctx.t("searching"))

    try:
        await _play_body(client, message, ctx, progress, media, query, reply, video=video, force=force, mix=mix)
    except asyncio.TimeoutError:
        log.warning("play timed out in %s for %r", chat_id, query)
        await _edit_or_send(message, progress, "⏱ That took too long (the music source is not answering). Try again, "
                                               "or ask the owner to check /diag.")
    except Exception:
        log.exception("play failed in %s for %r", chat_id, query)
        await _edit_or_send(message, progress, ctx.t("play_failed"))


async def _play_body(client, message, ctx, progress, media, query, reply, *, video, force, mix):
    chat_id = message.chat.id
    err = await asyncio.wait_for(player.ensure_assistant(chat_id), 30)
    if err:
        return await _edit_or_send(message, progress, f"❌ {esc(err)}")

    if media and not query:
        got = await _telegram_track(client, reply, video)
        if isinstance(got, str):
            return await _edit_or_send(message, progress, got)
        tracks = [got]
    elif mix:
        tracks = await asyncio.wait_for(_mix_tracks(query), config.SEARCH_TIMEOUT)
    else:
        tracks = await asyncio.wait_for(music_search.resolve_many(query, config.MAX_PLAYLIST_IMPORT),
                                        config.SEARCH_TIMEOUT)
    if not tracks:
        return await _edit_or_send(message, progress, ctx.t("not_found"))

    uid, name = _requester(message)
    status, pos, extra = await asyncio.wait_for(
        enqueue_tracks(chat_id, tracks, uid, name, video=video, force=force), config.SEARCH_TIMEOUT * 2)
    await _finish(message, ctx, progress, status, pos, extra, tracks[0])


def _register(names, **kw):
    @Client.on_message(filters.command(with_silent(names)) & filters.group)
    @group_cmd
    async def handler(client, message, ctx):
        await do_play(client, message, ctx, **kw)

    return handler


play_cmd = _register(guards.PLAY)
vplay_cmd = _register(guards.VPLAY, video=True)
fplay_cmd = _register(guards.FPLAY, force=True)
fvplay_cmd = _register(guards.FVPLAY, video=True, force=True)
mix_cmd = _register(guards.MIX, mix=True)


@Client.on_message(filters.command(with_silent(guards.SEARCH)) & filters.group)
@group_cmd
async def search_cmd(client, message, ctx):
    if not await can_play(client, message, ctx.settings):
        return await ui.reply(message, ctx.t("play_restricted"))
    query = query_of(message)
    if not query:
        return await ui.reply(message, "Usage: <code>/search song name</code>")
    tracks = await music_search.search(query, 5)
    if not tracks:
        return await ui.reply(message, ctx.t("not_found"))
    SEARCH_CACHE[message.chat.id] = (tracks, False)
    await ui.reply(message, "🔎 <b>Pick a track:</b>", search_results(tracks))


@Client.on_message(filters.command(["play", "vplay", "mix", "search"]) & filters.private)
async def play_private(client, message):
    await ui.reply(message, "Add me to a group and use /play there. 🎵")
