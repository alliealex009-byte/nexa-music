"""The live "now playing" card: song image, moving progress bar, controls, optional karaoke line.

One card per chat. It is a photo message (the song's thumbnail) whose caption is re-edited every few seconds
while the song plays. A new song replaces the card; stopping or finishing ends it.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

import config
from database import groups as groups_db
from services import botapi, lyrics, player, queue_manager, ui
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


def thumbnail_for(track: Track) -> str:
    """Image URL for the card: the track's own thumbnail, a YouTube still, or the welcome banner."""
    if track.thumbnail.startswith("http"):
        return track.thumbnail
    m = YT_ID.search(track.url or "")
    if m:
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
    return config.WELCOME_IMAGE or ""


def caption(chat_id: int, track: Track, settings: dict, lines: list | None = None, lang: str = "en") -> str:
    from services.i18n import t

    paused = chat_id in player.manual_paused or chat_id in player.auto_paused
    pos = player.position(chat_id)
    head = ("⏸ <b>Paused</b>" if paused else f"{ui.em('play', '▶️')} <b>{t(lang, 'now_playing')}</b>")
    name = f'<a href="{esc(track.url)}">{esc(track.title)}</a>' if track.url.startswith("http") else esc(track.title)
    extra = " • 🎬 Video" if track.video else ""
    lines_out = [head, f"<b>{name}</b>", "", f"<code>{progress_bar(pos, track.duration)}</code>"]
    lines_out.append(f"👤 {esc(track.requested_name or '—')}{extra}"
                     f"   ♾ Autoplay {'on' if settings.get('autoplay') else 'off'}")
    if settings.get("karaoke") and lines:
        words = lyrics.line_at(lines, pos + 0.5)
        if words:
            lines_out.append(f"\n🎤 <i>{esc(words)}</i>")
    text = "\n".join(lines_out)
    # a photo caption holds 1024 visible characters; titles are the only unbounded part
    if len(strip_html(text)) > 1000:
        text = text.replace(esc(track.title), esc(track.title[:80]) + "…")
    return text


def controls(chat_id: int, settings: dict, more: bool = False):
    from keyboards.inline import player_controls

    return player_controls(
        more=more,
        loop=queue_manager.loop_mode(chat_id),
        muted=chat_id in player.muted,
        autoplay=bool(settings.get("autoplay")),
        paused=chat_id in player.manual_paused or chat_id in player.auto_paused,
        lyrics=bool(settings.get("lyrics")),
    )


# ------------------------------------------------------------------ lifecycle
async def post(chat_id: int, track: Track, settings: dict | None = None) -> int | None:
    """Send a fresh card (replacing the old one) and start its live updates."""
    settings = settings or await groups_db.get_settings(chat_id)
    await stop_live(chat_id, delete=True)
    text = caption(chat_id, track, settings, lang=settings.get("language", "en"))
    rows = controls(chat_id, settings)
    photo = thumbnail_for(track)
    mid = await ui.send(chat_id, text, rows, photo=photo or None, sticky=True)
    has_photo = bool(photo)
    if mid is None and photo:  # Telegram couldn't fetch the image: fall back to a text card
        mid = await ui.send(chat_id, text, rows, sticky=True)
        has_photo = False
    if mid is None:
        return None
    card = Card(mid, track, has_photo)
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


async def refresh(chat_id: int, more: bool | None = None):
    """Re-render the card right now (after pause/resume/seek/autoplay...)."""
    card = cards.get(chat_id)
    if not card or queue_manager.current(chat_id) is not card.track:
        return
    if more is not None:
        card.more = more
    settings = await groups_db.get_settings(chat_id)
    await _edit(chat_id, card, settings)


async def _edit(chat_id: int, card: Card, settings: dict) -> bool:
    more = card.more
    text = caption(chat_id, card.track, settings, card.lines, settings.get("language", "en"))
    markup_key = (text, more, controls_key(chat_id, settings))
    if markup_key == card.last:
        return True
    params = {"chat_id": chat_id, "message_id": card.message_id, "parse_mode": "HTML"}
    method = "editMessageCaption" if card.has_photo else "editMessageText"
    if card.has_photo:
        params["caption"] = text
    else:
        params.update(text=text, link_preview_options={"is_disabled": True})
    try:
        await ui._post(method, params, controls(chat_id, settings, more))
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
        while cards.get(chat_id) is card and queue_manager.current(chat_id) is card.track:
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
