"""Voice chat playback via py-tgcalls (runs on the assistant account)."""
import asyncio
import logging
import time
from dataclasses import dataclass

from pytgcalls import filters
from pytgcalls.types import MediaStream

import config
from database import groups as groups_db
from services import audio_provider, queue_manager
from services.models import Track

log = logging.getLogger("player")

_bot = None
_assistant = None  # helper #1 (kept for older call sites)
_calls = None
_assistant_id: int | None = None


@dataclass(eq=False)
class Helper:
    """One assistant account (a Telegram user logged in with a session string) and its voice-call engine."""
    client: object
    calls: object
    index: int
    id: int | None = None
    username: str = ""
    name: str = ""
    source: str = "env"  # env | db
    db_id: int | None = None


_helpers: list[Helper] = []
_assign: dict[int, Helper] = {}  # chat -> the helper that plays there (one helper can serve many chats at once)

manual_paused: set[int] = set()  # paused by a person
auto_paused: set[int] = set()  # paused because nobody is listening
muted: set[int] = set()
_clock: dict[int, dict] = {}  # playback position tracking
_source: dict[int, str] = {}  # what ffmpeg is currently reading (for seek/restart)
_joined: set[int] = set()
last_error: dict[int, str] = {}

# UI hooks, set by handlers: async fn(chat_id, ...) -> None
hooks = {"now_playing": None, "notice": None, "state": None, "ended": None}


def setup(bot, assistant, calls):
    """Register the bot and helper #1. More helpers join later through add_helper()."""
    global _bot, _assistant, _calls
    _bot, _assistant, _calls = bot, assistant, calls
    _helpers.clear()
    _assign.clear()
    add_helper(assistant, calls)


def add_helper(client, calls, source: str = "env", db_id: int | None = None) -> Helper:
    helper = Helper(client=client, calls=calls, index=len(_helpers) + 1, source=source, db_id=db_id)
    _helpers.append(helper)
    _wire(calls)
    return helper


def helpers() -> list[Helper]:
    return list(_helpers)


def remove_helper(helper: Helper):
    _helpers.remove(helper)
    for chat in [c for c, h in _assign.items() if h is helper]:
        _assign.pop(chat, None)
        _joined.discard(chat)
    for n, h in enumerate(_helpers, 1):
        h.index = n


def helper_for(chat_id: int) -> Helper:
    return _assign.get(chat_id) or _helpers[0]


def _load(helper: Helper) -> int:
    return sum(1 for h in _assign.values() if h is helper)


def _wire(calls):
    @calls.on_update(filters.stream_end)
    async def _on_end(_, update):
        await play_next(update.chat_id)

    try:  # voice chat closed / assistant removed -> drop the session
        from pytgcalls.types import ChatUpdate

        closed = ChatUpdate.Status.CLOSED_VOICE_CHAT | ChatUpdate.Status.KICKED | ChatUpdate.Status.LEFT_GROUP

        @calls.on_update(filters.chat_update(closed))
        async def _on_closed(_, update):
            log.info("call closed in %s", update.chat_id)
            _reset(update.chat_id)
            queue_manager.clear(update.chat_id)
    except Exception:
        log.warning("chat_update filter not available; relying on the watchdog")


async def _notice(chat_id: int, text: str):
    fn = hooks.get("notice")
    if fn:
        try:
            await fn(chat_id, text)
        except Exception:
            log.exception("notice hook")


def _fire(name: str, chat_id: int):
    """Run a UI hook in the background (card refresh / card end); never breaks playback."""
    fn = hooks.get(name)
    if not fn:
        return
    try:
        asyncio.get_running_loop().create_task(_safe(fn, chat_id))
    except RuntimeError:
        pass


async def _safe(fn, chat_id: int):
    try:
        await fn(chat_id)
    except Exception:
        log.exception("ui hook")


def _reset(chat_id: int):
    _fire("ended", chat_id)
    manual_paused.discard(chat_id)
    auto_paused.discard(chat_id)
    muted.discard(chat_id)
    _clock.pop(chat_id, None)
    _source.pop(chat_id, None)


# ------------------------------------------------------------------ assistant presence
async def helper_me(helper: Helper):
    me = await helper.client.get_me()
    helper.id, helper.username = me.id, me.username or ""
    helper.name = " ".join(x for x in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if x)
    return me


async def assistant_info(helper: Helper | None = None):
    """Profile of a helper account (helper #1 by default)."""
    global _assistant_id
    helper = helper or _helpers[0]
    me = await helper_me(helper)
    if helper is _helpers[0]:
        _assistant_id = me.id
    return me


async def assistant_id(chat_id: int | None = None) -> int:
    helper = helper_for(chat_id) if chat_id is not None else _helpers[0]
    if helper.id is None:
        await helper_me(helper)
    return helper.id  # type: ignore[return-value]


async def _member_state(chat_id: int, helper: Helper) -> str:
    """'member' | 'banned' | 'none'"""
    if helper.id is None:
        await helper_me(helper)
    try:
        member = await _bot.get_chat_member(chat_id, helper.id)
    except Exception:
        return "none"
    status = str(getattr(member, "status", "")).lower()
    if "banned" in status:
        return "banned"
    return "none" if "left" in status else "member"


async def _choose_helper(chat_id: int) -> Helper:
    """A helper already in the group, else the least busy one that isn't banned there."""
    ordered = sorted(_helpers, key=lambda h: (_load(h), h.index))
    if len(ordered) == 1:
        return ordered[0]
    states = {h: await _member_state(chat_id, h) for h in ordered}
    for h in ordered:
        if states[h] == "member":
            return h
    for h in ordered:
        if states[h] != "banned":
            return h
    return ordered[0]


async def ensure_assistant(chat_id: int) -> str | None:
    """Make sure a helper account is in the group. Returns an error text or None."""
    if chat_id in _joined and chat_id in _assign:
        return None
    if chat_id not in _assign:
        _assign[chat_id] = await _choose_helper(chat_id)
        _joined.discard(chat_id)
    helper = _assign[chat_id]
    if chat_id in _joined:
        return None
    me = await assistant_info(helper)
    state = await _member_state(chat_id, helper)
    if state == "banned":
        return f"The assistant (@{me.username}) is banned in this group. Unban it and try again."
    if state == "member":
        _joined.add(chat_id)
        return None
    if not config.AUTO_JOIN_ASSISTANT:
        return f"Add the assistant account @{me.username} to this group first."
    try:
        chat = await _bot.get_chat(chat_id)
        target = chat.username or await _bot.export_chat_invite_link(chat_id)
        await helper.client.join_chat(target)
        _joined.add(chat_id)
        return None
    except Exception as e:
        name = type(e).__name__
        log.info("assistant auto-join failed: %s", name)
        if name == "UserAlreadyParticipant":
            _joined.add(chat_id)
            return None
        if name == "InviteRequestSent":
            return (
                f"This group needs admin approval for new members. I sent a join request for @{me.username}: "
                "approve it under the group's join requests (or add the assistant manually), then try again."
            )
        return (
            f"I couldn't add the assistant automatically. Add @{me.username} to this group "
            "(or make me an admin with the invite-users right) and try again."
        )


# ------------------------------------------------------------------ position tracking
def position(chat_id: int) -> int:
    c = _clock.get(chat_id)
    if not c:
        return 0
    pos = c["base"] + ((time.monotonic() - c["t0"]) if c["t0"] else 0)
    return int(pos)


def _clock_start(chat_id: int, base: float = 0):
    _clock[chat_id] = {"base": base, "t0": time.monotonic()}


def _clock_pause(chat_id: int):
    c = _clock.get(chat_id)
    if c and c["t0"]:
        c["base"] += time.monotonic() - c["t0"]
        c["t0"] = None


def _clock_resume(chat_id: int):
    c = _clock.get(chat_id)
    if c and not c["t0"]:
        c["t0"] = time.monotonic()


# ------------------------------------------------------------------ streaming
def _ffmpeg_input_args(src: str, seek: int) -> str:
    """Options placed before the input: reconnect on network hiccups (stuttering/cut-off audio) and optional seek."""
    parts = []
    if src.startswith(("http://", "https://")):
        parts.append("-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
    if seek:
        parts.append(f"-ss {int(seek)}")
    return " ".join(parts)


def _media(src: str, video: bool, seek: int = 0):
    kwargs = {}
    extra = _ffmpeg_input_args(src, seek)
    if extra:
        kwargs["ffmpeg_parameters"] = extra
    flags = getattr(MediaStream, "Flags", None)
    if flags is not None and not video:
        kwargs["video_flags"] = flags.IGNORE
    try:  # clean, full-band audio instead of the low default quality
        from pytgcalls.types import AudioQuality

        kwargs["audio_parameters"] = getattr(AudioQuality, config.AUDIO_QUALITY.upper(), AudioQuality.HIGH)
    except Exception:
        pass
    if video:
        try:
            from pytgcalls.types import VideoQuality

            kwargs["video_parameters"] = VideoQuality.SD_480p
        except Exception:
            pass
    return MediaStream(src, **kwargs)


async def _start_stream(chat_id: int, track: Track, seek: int = 0) -> bool:
    src = await audio_provider.get_source(track)
    if not src:
        last_error[chat_id] = track.error or "source"
        return False
    try:
        await helper_for(chat_id).calls.play(chat_id, _media(src, track.video, seek))
    except Exception as e:
        name = type(e).__name__
        last_error[chat_id] = "no_vc" if "NoActiveGroupCall" in name else "play"
        log.warning("play failed in %s: %s", chat_id, name)
        return False
    _source[chat_id] = src
    manual_paused.discard(chat_id)
    auto_paused.discard(chat_id)
    muted.discard(chat_id)
    _clock_start(chat_id, seek)
    settings = await groups_db.get_settings(chat_id)
    if settings["volume"] != 100:
        try:
            await helper_for(chat_id).calls.change_volume_call(chat_id, settings["volume"])
        except Exception:
            pass
    return True


async def play_or_queue(chat_id: int, track: Track) -> tuple[str, int]:
    """Returns ('playing'|'queued'|'full'|'error', position)."""
    if queue_manager.current(chat_id) is None:
        queue_manager.add(chat_id, track)
        nxt = queue_manager.next_track(chat_id)
        if not await _start_stream(chat_id, nxt):
            queue_manager.clear(chat_id)
            return "error", 0
        return "playing", 0
    pos = queue_manager.add(chat_id, track)
    return ("full", 0) if pos is None else ("queued", pos)


async def play_now(chat_id: int, tracks: list[Track]) -> tuple[str, int]:
    """Play immediately, ahead of the queue (the /fplay family)."""
    for t in reversed(tracks):
        queue_manager.add_front(chat_id, t)
    if queue_manager.current(chat_id) is None:
        nxt = queue_manager.next_track(chat_id)
        if not await _start_stream(chat_id, nxt):
            queue_manager.clear(chat_id)
            return "error", 0
        return "playing", 0
    nxt = await play_next(chat_id, skipped=True, announce=False)
    return ("playing", 0) if nxt else ("error", 0)


async def play_next(chat_id: int, skipped: bool = False, announce: bool = True) -> Track | None:
    last = queue_manager.current(chat_id)
    queue_manager.finish_current(chat_id, skipped)
    tried_autoplay = False
    while True:
        nxt = queue_manager.next_track(chat_id)
        if nxt is None:
            settings = await groups_db.get_settings(chat_id)
            if settings["autoplay"] and last and not tried_autoplay:
                tried_autoplay = True
                from services import autoplay

                for t in await autoplay.pick(chat_id, last):
                    queue_manager.add(chat_id, t)
                if queue_manager.upcoming(chat_id):
                    continue
            await leave(chat_id)
            if announce:
                await _notice(chat_id, "queue_finished")
            return None
        if await _start_stream(chat_id, nxt):
            fn = hooks.get("now_playing")
            if announce and fn:
                try:
                    await fn(chat_id, nxt)
                except Exception:
                    log.exception("now_playing hook")
            return nxt
        await _notice(chat_id, f"skip_failed:{nxt.title}")


async def restart_current(chat_id: int) -> bool:
    """Re-open the current track at its last known position (call dropped)."""
    track = queue_manager.current(chat_id)
    if not track:
        return False
    return await _start_stream(chat_id, track, seek=position(chat_id))


async def leave(chat_id: int):
    try:
        await helper_for(chat_id).calls.leave_call(chat_id)
    except Exception:
        pass
    _reset(chat_id)


async def stop(chat_id: int):
    queue_manager.clear(chat_id)
    await leave(chat_id)


async def pause(chat_id: int):
    await helper_for(chat_id).calls.pause(chat_id)
    manual_paused.add(chat_id)
    _clock_pause(chat_id)
    _fire("state", chat_id)


async def resume(chat_id: int):
    await helper_for(chat_id).calls.resume(chat_id)
    manual_paused.discard(chat_id)
    auto_paused.discard(chat_id)
    _clock_resume(chat_id)
    _fire("state", chat_id)


async def auto_pause(chat_id: int) -> bool:
    if chat_id in manual_paused or chat_id in auto_paused:
        return False
    await helper_for(chat_id).calls.pause(chat_id)
    auto_paused.add(chat_id)
    _clock_pause(chat_id)
    _fire("state", chat_id)
    return True


async def auto_resume(chat_id: int) -> bool:
    """Resume after listeners came back — never overrides a manual pause."""
    if chat_id not in auto_paused or chat_id in manual_paused:
        return False
    await helper_for(chat_id).calls.resume(chat_id)
    auto_paused.discard(chat_id)
    _clock_resume(chat_id)
    _fire("state", chat_id)
    return True


async def skip(chat_id: int, announce: bool = True) -> Track | None:
    return await play_next(chat_id, skipped=True, announce=announce)


async def seek(chat_id: int, delta: int) -> int | None:
    """Jump `delta` seconds (negative = back). Returns the new position, or None if not possible."""
    track = queue_manager.current(chat_id)
    src = _source.get(chat_id)
    if not track or not src or not track.duration:
        return None
    target = max(0, position(chat_id) + delta)
    if target >= track.duration - 1:
        return None
    try:
        await helper_for(chat_id).calls.play(chat_id, _media(src, track.video, target))
    except Exception:
        log.exception("seek failed")
        return None
    was_paused = chat_id in manual_paused or chat_id in auto_paused
    _clock_start(chat_id, target)
    if was_paused:
        try:
            await helper_for(chat_id).calls.pause(chat_id)
            _clock_pause(chat_id)
        except Exception:
            pass
    _fire("state", chat_id)
    return target


async def mute(chat_id: int):
    await helper_for(chat_id).calls.mute(chat_id)
    muted.add(chat_id)


async def unmute(chat_id: int):
    await helper_for(chat_id).calls.unmute(chat_id)
    muted.discard(chat_id)


async def set_volume(chat_id: int, volume: int):
    await helper_for(chat_id).calls.change_volume_call(chat_id, volume)


def sources_in_use() -> set[str]:
    return set(_source.values())


async def participants(chat_id: int):
    return await helper_for(chat_id).calls.get_participants(chat_id)
