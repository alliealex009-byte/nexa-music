import config
from services import helptext
from services.ui import b


def main_menu(bot_username: str = "", is_owner: bool = False):
    rows = []
    if bot_username:
        rows.append([b("✦ ADD ME TO YOUR GROUP ✦", url=f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages+invite_users+manage_video_chats",
                       style="primary", emoji="add")])
    rows += [
        [b("🎵 Play Music", "menu:play", style="success", emoji="play"),
         b("🔎 Search", "menu:search", style="primary", emoji="search")],
        [b("📋 Queue", "menu:queue", style="primary", emoji="queue"),
         b("🎧 Playlists", "menu:playlists", style="success", emoji="playlist")],
        [b("⚙️ Settings", "menu:settings", style="primary", emoji="settings"),
         b("💎 Premium", "menu:premium", style="success", emoji="premium")],
    ]
    links = []
    if config.SUPPORT_GROUP:
        links.append(b("💬 Support", url=f"https://t.me/{config.SUPPORT_GROUP}", style="success", emoji="support"))
    if config.UPDATES_CHANNEL:
        links.append(b("📢 Updates", url=f"https://t.me/{config.UPDATES_CHANNEL}", style="primary", emoji="updates"))
    if links:
        rows.append(links)
    rows.append([b("📚 Help & Commands", "help:home", style="success", emoji="help")])
    if is_owner:
        rows.append([b("🛠 Owner Panel", "own:home", style="danger", emoji="admin")])
    return rows


def back_button(to: str = "menu:home"):
    return [[b("⬅️ Back", to, emoji="back")]]


def play_menu():
    return [
        [b("🎵 Playback", "help:play", style="primary", emoji="music"),
         b("🔀 Mix & Autoplay", "help:autoplay", emoji="mix")],
        [b("🎤 Lyrics & Tools", "help:owner", emoji="lyrics")],
        [b("⬅️ Back", "menu:home", emoji="back")],
    ]


def help_hub():
    rows, row = [], []
    for page in helptext.ORDER:
        row.append(b(helptext.TITLES[page], f"help:{page}", style="primary"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([b("⬅️ Back", "menu:home", emoji="back"), b("❌ Close", "close", style="danger", emoji="close")])
    return rows


def help_page(page: str):
    siblings = [p for p in helptext.ORDER if p != page]
    rows, row = [], []
    for p in siblings:
        row.append(b(helptext.TITLES[p], f"help:{p}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([b("⬅️ Back", "help:home", emoji="back")])
    return rows


def player_controls(more: bool = False, loop: str = "off", muted: bool = False, autoplay: bool = False,
                    paused: bool = False, lyrics: bool = False):
    if not more:
        middle = (b("▶️ Resume", "ctl:resume", style="success", emoji="resume") if paused
                  else b("⏸ Pause", "ctl:pause", style="primary", emoji="pause"))
        rows = [
            [b("⏪ 10s", "ctl:seekb"), middle, b("10s ⏩", "ctl:seekf")],
            [b("⏭ Skip", "ctl:skip", style="primary", emoji="skip"), b("⏹ Stop", "ctl:stop", style="danger", emoji="stop")],
            [b("♾ Autoplay: " + ("on" if autoplay else "off"), "ctl:autoplay",
               style="success" if autoplay else None, emoji="autoplay"),
             b("📋 Queue", "ctl:queue", emoji="queue")],
        ]
        last = [b("➕ More", "ctl:more", emoji="add")]
        if lyrics:
            last.insert(0, b("🎤 Lyrics", "ctl:lyrics", emoji="lyrics"))
        rows.append(last)
        return rows
    loop_label = {"off": "🔁 Loop: off", "track": "🔂 Loop: track", "queue": "🔁 Loop: queue"}[loop]
    return [
        [b("🔊 Unmute" if muted else "🔇 Mute", "ctl:unmute" if muted else "ctl:mute", emoji="mute"),
         b(loop_label, "ctl:loop", emoji="loop")],
        [b("🔀 Shuffle", "ctl:shuffle", emoji="shuffle"),
         b("♾ Autoplay: " + ("on" if autoplay else "off"), "ctl:autoplay", emoji="autoplay")],
        [b("⬅️ Back", "ctl:back", emoji="back"), b("❌ Close", "close", style="danger", emoji="close")],
    ]


def search_results(tracks, video: bool = False):
    prefix = "vpick" if video else "pick"
    rows = [[b(f"{i + 1}. {t.title[:45]}", f"{prefix}:{i}")] for i, t in enumerate(tracks)]
    rows.append([b("❌ Close", "close", style="danger", emoji="close")])
    return rows


def playlists_panel(playlists):
    rows = [[b(f"🎧 {name}", f"pl:open:{pid}", emoji="playlist")] for pid, name in playlists]
    rows.append([b("⬅️ Back", "menu:home", emoji="back")])
    return rows


def playlist_actions(pid: int):
    return [
        [b("▶️ Play all", f"pl:play:{pid}", style="success", emoji="play")],
        [b("🗑 Delete", f"pl:del:{pid}", style="danger", emoji="delete")],
        [b("⬅️ Back", "menu:playlists", emoji="back")],
    ]
