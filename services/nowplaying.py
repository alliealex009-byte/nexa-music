"""The live "now playing" card: song image, moving progress bar, controls, optional karaoke line.

One card per chat. It is a photo message (the song's thumbnail) whose caption is re-edited every few seconds
while the song plays. A new song replaces the card; stopping or finishing ends it.
"""
import asyncio
import time
import logging
import re
from dataclasses import dataclass, field

import config
from database import groups as groups_db
from services import botapi, cardimg, lyrics, player, queue_manager, ui
from services.models import Track
from utils.text import esc, fmt_clock, strip_html

log = logging.getLogger("nowplaying")

BAR_WIDTH = 12
YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


@dataclass
class Card:
    message_id: int
    track: Track
    has_photo: bool
    task: asyncio.Task | None = None
    last: object = None  # what was last rendered (text + control state)
    lines: list = field(default_factory=list)
    lines_loaded: bool = False
    more: bool = False  # showing the "More" button page
    cover: bytes | None = None
    fallback: bytes | None = None
    img_at: float = 0.0  # when the card image was last re-rendered
    img_fail: int = 0
    status: str | None = None  # e.g. "downloading audio…" while the next track loads


cards: dict[int, Card] = {}


# ------------------------------------------------------------------ pure helpers
def progress_bar(position: int, duration: int, width: int = BAR_WIDTH) -> str:
    """'1:23 ━━●────── 3:45' (a live stream, duration 0, shows only the elapsed time)."""
    if not duration:
        return f"🔴 {fmt_clock(position)}"
    position = max(0, min(position, duration))
    knob = min(width - 1, int(position / duration * width))
    track = "━" * knob + "●" + "─" * (width - 1 - knob)
    return f"{fmt_clock(position)} {track} {fmt_clock(duration)}"


def button_bar(position: int, duration: int, width: int = 8) -> str:
    """'0:19 ▬▬▭▭▭▭▭▭ 3:04' for the progress button."""
    if not duration:
        return f"🔴 LIVE  {fmt_clock(position)}"
    position = max(0, min(position, duration))
    filled = min(width, int(position / duration * width))
    return f"{fmt_clock(position)} {'▬' * filled}{'▭' * (width - filled)} {fmt_clock(duration)}"


def thumbnail_for(track: Track) -> str:
    """Image URL for the card: the track's own thumbnail, a YouTube still, or the welcome banner."""
    if track.thumbnail.startswith("http"):
        return track.thumbnail
    m = YT_ID.search(track.url or "")
    if m:
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
    return config.WELCOME_IMAGE or ""


def caption(chat_id: int, track: Track, settings: dict, lines: list | None = None, lang: str = "en") -> str:
    paused = chat_id in player.manual_paused or chat_id in player.auto_paused
    pos = player.position(chat_id)
    head = "ᴘᴀᴜsᴇᴅ" if paused else "sᴛʀᴇᴀᴍɪɴɢ ɪɴ ᴠᴄ"
    icon = "⏸" if paused else ui.em("play", "▶️")
    name = song_link(track)
    extra = " • 🎬 Video" if track.video else ""
    dur = fmt_clock(track.duration) if track.duration else "LIVE"
    body = [f"<b>TRACK:</b> {name}{extra}", f"<b>DURATION:</b> {dur}",
            f"<b>REQUESTED BY:</b> {esc(track.requested_name or '—')}"]
    if settings.get("karaoke") and lines:
        words = lyrics.line_at(lines, pos + 0.5)
        if words:
            body.append(f"🎤 <i>{esc(words)}</i>")
    text = f"<blockquote>{icon} <b>{head}</b></blockquote>\n<blockquote expandable>" + "\n".join(body) + "</blockquote>"
    # a photo caption holds 1024 visible characters; titles are the only unbounded part
    if len(strip_html(text)) > 1000:
        text = text.replace(esc(track.title), esc(track.title[:80]) + "…")
    return text


def song_link(track: Track) -> str:
    """Song title linked to the bot (t.me/<bot>?start=song_<id>) instead of a raw YouTube link."""
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", track.url or "")
    if m and ui.bot_username:
        return f'<a href="https://t.me/{ui.bot_username}?start=song_{m.group(1)}">{esc(track.title)}</a>'
    return esc(track.title)


def _bar(pct: int, n: int = 10) -> str:
    filled = max(0, min(n, round(pct / 100 * n)))
    return "▰" * filled + "▱" * (n - filled)


def status_text(key: str) -> str:
    if key.startswith("dl:"):
        try:
            _, pct, speed, eta = key.split(":")
            pct, speed, eta = int(pct), int(speed), int(eta)
        except ValueError:
            return "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ ..."
        extra = ([f"{speed / 1048576:.1f} MB/s"] if speed else []) + ([f"{eta}s left"] if eta else [])
        tail = ("  ·  " + " · ".join(extra)) if extra else ""
        return f"ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ ...\n{_bar(pct)} {pct}%{tail}"
    return {
        "downloading": "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴀᴜᴅɪᴏ ...",
        "starting": "sᴛᴀʀᴛɪɴɢ sᴛʀᴇᴀᴍ ...",
        "searching": "sᴇᴀʀᴄʜɪɴɢ ...",
    }.get(key, key)


def controls(chat_id: int, settings: dict, more: bool = False, track: Track | None = None):
    from keyboards.inline import player_controls

    track = track or queue_manager.current(chat_id)
    return player_controls(
        more=more,
        loop=queue_manager.loop_mode(chat_id),
        muted=chat_id in player.muted,
        autoplay=bool(settings.get("autoplay")),
        paused=chat_id in player.manual_paused or chat_id in player.auto_paused,
        lyrics=bool(settings.get("lyrics")),
        bar=button_bar(player.position(chat_id), track.duration) if track else None,
    )


# ------------------------------------------------------------------ lifecycle
async def post(chat_id: int, track: Track, settings: dict | None = None) -> int | None:
    """Send a fresh card (replacing the old one) and start its live updates. Never raises: if anything in the
    fancy path breaks, a plain text card is sent instead so the user always sees what is playing."""
    try:
        return await _post_card(chat_id, track, settings)
    except Exception as e:
        log.exception("now-playing card failed")
        player.errors.append((time.time(), chat_id, "card", repr(e)))
        try:
            return await ui.send(chat_id, f"▶️ <b>{esc(track.title)}</b>\nRequested by {esc(track.requested_name or '—')}",
                                 sticky=True)
        except Exception:
            return None


async def _post_card(chat_id: int, track: Track, settings: dict | None = None) -> int | None:
    settings = settings or await groups_db.get_settings(chat_id)
    await stop_live(chat_id, delete=True)
    text = caption(chat_id, track, settings, lang=settings.get("language", "en"))
    rows = controls(chat_id, settings, track=track)
    photo = thumbnail_for(track)
    mid, has_photo = None, bool(photo)
    cover = await cardimg.fetch(photo) if photo else None
    fallback = await cardimg.fetch(config.WELCOME_IMAGE)
    img = await cardimg.render(cardimg.render_player, cover, track.title,
                               f"Requested by {track.requested_name or '—'}", track.duration,
                               fallback=fallback) if cover or not photo else None
    if img:
        mid = await ui.send(chat_id, text, rows, photo_bytes=img, sticky=True)
        has_photo = True
    if mid is None:
        mid = await ui.send(chat_id, text, rows, photo=photo or None, sticky=True)
    if mid is None and photo:  # Telegram couldn't fetch the image: fall back to a text card
        mid = await ui.send(chat_id, text, rows, sticky=True)
        has_photo = False
    if mid is None:
        log.warning("now-playing card could not be sent in %s", chat_id)
        player.errors.append((time.time(), chat_id, "card", "send failed"))
        return None
    log.info("now-playing card sent in %s (photo=%s, image=%s)", chat_id, has_photo, bool(img))
    card = Card(mid, track, has_photo)
    card.cover, card.fallback, card.img_at = cover, fallback, time.monotonic()
    card.img_fail = 0 if img else 99  # no rendered image on this card: never try to swap pictures
    cards[chat_id] = card
    card.task = asyncio.get_event_loop().create_task(_live(chat_id, card))
    return mid


async def stop_live(chat_id: int, delete: bool = False, final: str | None = None):
    card = cards.pop(chat_id, None)
    if not card:
        return
    if card.task and card.task is not asyncio.current_task():
        card.task.cancel()
    if delete:
        await ui.delete(chat_id, card.message_id)
    elif final:
        await ui.edit(chat_id, card.message_id, final, None, caption=card.has_photo)


async def show_status(chat_id: int, key: str):
    """Swap the live card's text for e.g. 'downloading audio…' while the next track loads."""
    card = cards.get(chat_id)
    if not card:
        return False
    card.status = status_text(key)
    await _edit(chat_id, card, {})
    return True


async def drop(chat_id: int):
    """Remove the card (the next track could not be loaded)."""
    await stop_live(chat_id, delete=True)


async def refresh(chat_id: int, more: bool | None = None):
    """Re-render the card right now (after pause/resume/seek/autoplay...)."""
    card = cards.get(chat_id)
    if not card or queue_manager.current(chat_id) is not card.track:
        return
    if more is not None:
        card.more = more
    card.img_at = 0.0  # pause / resume / seek: redraw the picture too
    settings = await groups_db.get_settings(chat_id)
    await _edit(chat_id, card, settings)


async def _edit(chat_id: int, card: Card, settings: dict) -> bool:
    more = card.more
    if card.status:
        text, rows = f"<blockquote>{card.status}</blockquote>", None
    else:
        text, rows = caption(chat_id, card.track, settings, card.lines, settings.get("language", "en")), "controls"
    markup_key = (text, more, controls_key(chat_id, settings), button_bar(player.position(chat_id), card.track.duration))
    if markup_key == card.last:
        return True
    params = {"chat_id": chat_id, "message_id": card.message_id, "parse_mode": "HTML"}
    method = "editMessageCaption" if card.has_photo else "editMessageText"
    if card.has_photo:
        params["caption"] = text
    else:
        params.update(text=text, link_preview_options={"is_disabled": True})
    use_image = (rows and card.has_photo and card.img_fail < 3 and config.IMAGE_UPDATE_SECONDS > 0
                 and time.monotonic() - card.img_at >= config.IMAGE_UPDATE_SECONDS)
    try:
        if use_image:
            img = await cardimg.render(
                cardimg.render_player, card.cover, card.track.title,
                f"Requested by {card.track.requested_name or '—'}", card.track.duration,
                chat_id in player.manual_paused or chat_id in player.auto_paused,
                card.fallback, player.position(chat_id))
            if img:
                caption_text = text if ui._flags["icons"] else ui.strip_emoji_tags(text)
                media = {"type": "photo", "media": "attach://card", "caption": caption_text, "parse_mode": "HTML"}
                try:
                    await ui._post("editMessageMedia", {"chat_id": chat_id, "message_id": card.message_id, "media": media},
                                   controls(chat_id, settings, more, card.track), {"card": ("card.jpg", img, "image/jpeg")})
                    card.img_at, card.img_fail = time.monotonic(), 0
                    card.last = markup_key
                    return True
                except botapi.BotApiError as e:
                    if "not modified" not in e.description.lower() and "not found" not in e.description.lower():
                        card.img_fail += 1
                        card.img_at = time.monotonic()
                        log.info("card image update failed (%s)", e.description)
                    else:
                        raise
        await ui._post(method, params, controls(chat_id, settings, more, card.track) if rows else None)
    except botapi.BotApiError as e:
        desc = e.description.lower()
        if "not modified" in desc:
            card.last = markup_key
            return True
        if "not found" in desc or "can't be edited" in desc or "message to edit" in desc:
            return False  # someone deleted the card
        if e.code == 429:
            await asyncio.sleep(min(30, 3))
        return True
    except Exception:
        return True
    card.last = markup_key
    return True


def controls_key(chat_id: int, settings: dict):
    return (chat_id in player.manual_paused, chat_id in player.auto_paused, chat_id in player.muted,
            bool(settings.get("autoplay")), bool(settings.get("lyrics")), queue_manager.loop_mode(chat_id))


def interval(settings: dict) -> float:
    base = config.KARAOKE_UPDATE_SECONDS if settings.get("karaoke") else config.LIVE_UPDATE_SECONDS
    return max(base, 0.15 * len(cards))  # many groups at once: slow down to stay inside Telegram's limits


async def _live(chat_id: int, card: Card):
    try:
        while cards.get(chat_id) is card and (queue_manager.current(chat_id) is card.track or card.status):
            settings = await groups_db.get_settings(chat_id)
            if settings.get("karaoke") and not card.lines_loaded:
                card.lines_loaded = True
                card.lines = await lyrics.find_synced(card.track.title, card.track.duration)
            if not await _edit(chat_id, card, settings):
                cards.pop(chat_id, None)
                return
            await asyncio.sleep(interval(settings))
        # the song changed under us (skip, or the next one is still loading): drop this card. When the queue is
        # empty the "ended" hook turns the card into a final message instead.
        if cards.get(chat_id) is card and queue_manager.current(chat_id) is not None:
            cards.pop(chat_id, None)
            await ui.delete(chat_id, card.message_id)
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("live card")
