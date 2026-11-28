"""Help pages (HTML). Each page is opened from the /help hub via a sub-menu button."""
import re

import config

PAGES = {
    "play": (
        "🎵 <b>Playback</b>\n\n"
        "/play [song | link] — play from YouTube, Spotify, Apple Music, SoundCloud, JioSaavn, Deezer and more\n"
        "/mix [song] — queue a mix of related songs\n"
        "/vplay [song] — play a video in the voice chat\n"
        "/fplay [song] — play right now, ahead of the queue\n"
        "/fvplay [song] — play a video right now\n"
        "/splay /svplay /sfplay /sfvplay — same, but the final success message is hidden "
        "(progress and errors stay visible)\n"
        "/sskip /sstop /spause /sresume — silent controls; put an <code>s</code> in front of "
        "other playback commands for the same effect\n"
        "/search [song] — pick from results\n"
        "/lyrics [song] — lyrics of the current (or named) song\n"
        "<i>Reply to an audio/video file with /play to play it.</i>"
    ),
    "admin": (
        "🛡 <b>Admin commands</b>\n\n"
        "/skip — next track\n/pause · /resume\n"
        "/seek [seconds] — jump forward (use a minus sign to go back)\n"
        "/mute · /unmute — mute the stream\n/stop (/end) — stop and clear the queue\n"
        "/volume [1-200]\n\n"
        "<i>Administrator mode (see /settings) decides whether everyone or only admins and "
        "authorized users may use these.</i>"
    ),
    "queue": (
        "📋 <b>Queue &amp; access</b>\n\n"
        "/queue — what's playing and up next\n/remove [n] — remove track n\n/clear — empty the queue\n"
        "/shuffle — shuffle the queue\n/loop [off|track|queue]\n"
        "/auth [reply|id] — let a member use admin playback commands\n"
        "/unauth [reply|id] · /authlist\n/reload — refresh settings"
    ),
    "owner": (
        "👑 <b>Chat owner commands</b>\n\n"
        "/settings — play mode, administrator mode, command deletion, bot-message auto-delete "
        "(2–7 minutes), silent mode, language, auto-pause, idle auto-stop, autoplay\n"
        "/tagall [text] — mention everyone with emoji · /stoptag to stop"
    ),
    "playlist": (
        "🎧 <b>Playlists</b> (private chat with the bot)\n\n"
        "/createplaylist [name] · /deleteplaylist [name]\n"
        "/addtoplaylist [name] | [song or link] — or leave the song out while a track is playing\n"
        "/removefromplaylist [name] | [number]\n"
        "/playlistinfo [name] · /myplaylists\n"
        "/playplaylist [name] — queue a playlist in a group"
    ),
    "autoplay": (
        "♾ <b>Autoplay</b>\n\n"
        "/autoplay [on|off] — when the queue ends, keep playing related songs.\n"
        "When nobody is in the voice chat the music pauses, resumes when someone joins, and "
        "stops completely after a few minutes of silence to save server resources."
    ),
    "dev": (
        "🧑‍💻 <b>Developer commands</b> (bot owner)\n\n"
        "/owner — the owner panel: keys, proxies, cookies, emoji, premium, broadcast, diagnostics — all with buttons\n"
        "/id — show your Telegram ID · /diag — health check\n"
        "/stats — users, groups, calls, server load\n/av — active voice chats\n"
        "/clearass — clear caches and assistant state\n/leaveall — assistant leaves idle groups\n"
        "/logger [on|off] — send play/error logs to the log chat\n/ping\n"
        "<b>In a private chat:</b> /addkey /keys /rmkey · /addproxy /proxies /rmproxy /checkproxies · "
        "/cookies /setcookies /rmcookies · /setemoji /emojis /rmemoji · /grant /revoke /broadcast"
    ),
}

ORDER = ["play", "admin", "queue", "owner", "playlist", "autoplay", "dev"]
TITLES = {
    "play": "🎵 Playback", "admin": "🛡 Admin", "queue": "📋 Queue & Access", "owner": "👑 Chat Owner",
    "playlist": "🎧 Playlists", "autoplay": "♾ Autoplay", "dev": "🧑‍💻 Developer",
}


def hub_text() -> str:
    return (
        "📚 <b>Help &amp; commands</b>\n\n"
        "Pick a category below. Everything works from YouTube, Spotify, Apple Music, SoundCloud, "
        "JioSaavn, Deezer, Tidal, Amazon Music, Gaana, Wynk and plain links.\n\n"
        f"💬 @{config.SUPPORT_GROUP}"
    )


# ------------------------------------------------------------------ rich version (tables + collapsible sections)
def _cell(content: str) -> str:
    return f'<td align="left" valign="top">{content}</td>'


def _split(page: str):
    """(title, [(command, description)], [notes]) from a classic help page."""
    lines = [ln.strip() for ln in PAGES[page].split("\n")]
    title = re.sub(r"<[^>]+>", "", lines[0]).strip()
    rows, notes = [], []
    for ln in lines[1:]:
        if not ln:
            continue
        if ln.startswith("/"):
            cmd, _, desc = ln.partition(" — ")
            rows.append((cmd.strip(), desc.strip() or "—"))
        else:
            notes.append(ln)
    return title, rows, notes


def _table(rows) -> str:
    head = '<tr><th align="left" valign="top">Command</th><th align="left" valign="top">Description</th></tr>'
    body = "".join(f"<tr>{_cell(f'<code>{c}</code>')}{_cell(d)}</tr>" for c, d in rows)
    return f"<table bordered>{head}{body}</table>"


def rich_page(page: str) -> str:
    title, rows, notes = _split(page)
    out = [f"<h2>{title}</h2>"]
    if rows:
        out.append(_table(rows))
    out += [f"<p>{n}</p>" for n in notes]
    return "".join(out)


def rich_hub() -> str:
    out = ["<h2>📚 Help &amp; commands</h2>",
           "<blockquote>Fast, ads-free music for Telegram voice chats. Open a section below or use the buttons.</blockquote>"]
    for page in ORDER:
        title, rows, notes = _split(page)
        inner = (_table(rows) if rows else "") + "".join(f"<p>{n}</p>" for n in notes)
        out.append(f"<details><summary>{title}</summary>{inner}</details>")
    out.append("<p><i>Use the buttons below to go inside or back.</i></p>")
    return "".join(out)
