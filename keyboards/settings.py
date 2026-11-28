"""Settings hub and its sub-menus. Callbacks: st:open:<page> | st:tog:<key> | st:set:<key>:<value>."""
from services import i18n
from services.ui import b

PLAY_MODES = {"everyone": "👥 Everyone", "admins": "🛡 Admins only", "auth": "🔑 Admins + authorized"}
TOGGLES = {
    "admin_only": ("🛡 Administrator mode", "admin"),
    "delete_commands": ("🧹 Delete commands", "delete"),
    "silent": ("🤫 Silent mode", "silent"),
    "auto_pause": ("⏸ Auto-pause when VC empty", "pause"),
    "idle_stop": ("💤 Leave when VC stays empty", "stop"),
    "autoplay": ("♾ Autoplay", "autoplay"),
    "lyrics": ("🎤 Lyrics", "lyrics"),
    "karaoke": ("🎶 Karaoke mode", "karaoke"),
    "welcome": ("👋 Welcome card", "admin"),
    "join_accept": ("🛂 Auto-accept verified join requests", "admin"),
}


def _tick(v) -> str:
    return "✅" if v else "❌"


def _tog(label: str, key: str, value, emoji: str):
    """Toggle button: green when on, red when off."""
    return b(f"{_tick(value)} {label}", f"st:tog:{key}", style="success" if value else "danger", emoji=emoji)


def hub(s: dict):
    auto = f"{s['auto_delete']} min" if s["auto_delete"] else "off"
    rows = [
        [b(f"🎮 Play mode: {PLAY_MODES[s['play_mode']].split(' ', 1)[1]}", "st:open:play_mode", style="primary", emoji="play")],
        [_tog("Administrator mode", "admin_only", s["admin_only"], "admin"),
         _tog("Delete commands", "delete_commands", s["delete_commands"], "delete")],
        [b(f"🕑 Auto-delete: {auto}", "st:open:auto_delete", style="primary"),
         _tog("Silent mode", "silent", s["silent"], "silent")],
        [_tog("Auto-pause", "auto_pause", s["auto_pause"], "pause"),
         _tog("Idle auto-stop", "idle_stop", s["idle_stop"], "stop")],
        [_tog("Autoplay", "autoplay", s["autoplay"], "autoplay"),
         b(f"🌐 {i18n.LANG_NAMES.get(s['language'], s['language'])}", "st:open:language", style="primary", emoji="language")],
        [_tog("Lyrics", "lyrics", s["lyrics"], "lyrics"),
         _tog("Karaoke mode", "karaoke", s["karaoke"], "lyrics")],
        [_tog("Welcome card", "welcome", s["welcome"], "admin"),
         _tog("Auto-accept joins", "join_accept", s["join_accept"], "admin")],
        [b("❌ Close", "close", style="danger", emoji="close")],
    ]
    return rows


def _choices(key: str, options, current, label) -> list:
    rows, row = [], []
    for value in options:
        mark = "✅ " if value == current else ""
        row.append(b(f"{mark}{label(value)}", f"st:set:{key}:{value}", style="success" if value == current else None))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([b("⬅️ Back", "st:home", emoji="back")])
    return rows


def page(name: str, s: dict) -> tuple[str, list]:
    if name == "play_mode":
        return (
            "🎮 <b>Play mode</b>\nWho may start playback with /play and friends?",
            _choices("play_mode", list(PLAY_MODES), s["play_mode"], lambda v: PLAY_MODES[v]),
        )
    if name == "auto_delete":
        return (
            "🕑 <b>Auto-delete bot messages</b>\nDelete the bot's messages after 2–7 minutes (needs the "
            "delete-messages right).",
            _choices("auto_delete", [0, 2, 3, 4, 5, 6, 7], s["auto_delete"], lambda v: "Off" if v == 0 else f"{v} min"),
        )
    if name == "language":
        return (
            "🌐 <b>Language</b>",
            _choices("language", list(i18n.LANG_NAMES), s["language"], lambda v: i18n.LANG_NAMES[v]),
        )
    return i18n.t(s["language"], "settings_title"), hub(s)
