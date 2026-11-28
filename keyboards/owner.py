"""Owner panel keyboards. Callbacks: own:<area>:<action>[:arg]."""
from services import ui
from services.ui import b

BACK = b("⬅️ Back", "own:home", emoji="back")


def home(logger_on: bool, vplay_on: bool = True):
    return [
        [b("📊 Stats", "own:stats", style="primary"), b("🎧 Active VCs", "own:av", style="primary")],
        [b("🔑 API Keys", "own:keys", style="success"), b("🧦 Proxies", "own:proxies", style="success")],
        [b("🍪 Cookies", "own:cookies", style="success"), b("✨ Premium Emoji", "own:emoji", style="primary")],
        [b("💎 Premium Users", "own:premium", style="primary"), b("📣 Broadcast", "own:bc:start", style="primary")],
        [b(f"📝 Logger: {'ON' if logger_on else 'OFF'}", "own:logger", style="success" if logger_on else "danger"),
         b("🧹 Clear cache", "own:clear")],
        [b("🤖 Helpers", "own:helpers", style="success"), b("💾 Backup", "own:backup", style="success")],
        [b(f"🎬 Video play (/vplay): {'ON' if vplay_on else 'OFF'}", "own:vplay",
           style="success" if vplay_on else "danger")],
        [b("🔎 Run diagnostics", "own:diag", style="primary")],
        [b("❌ Close", "close", style="danger", emoji="close")],
    ]


def keys_menu(keys):
    rows = [[b("➕ Add key", "own:k:add", style="success")]]
    for kid, key, *_ in keys:
        rows.append([b(f"🗑 Remove #{kid} …{key[-4:]}", f"own:k:rm:{kid}", style="danger")])
    if keys:
        rows.append([b("🗑 Remove all", "own:k:all", style="danger")])
    rows.append([BACK])
    return rows


def proxies_menu(proxies):
    rows = [[b("➕ Add proxy", "own:p:add", style="success"), b("🔎 Check all", "own:p:check", style="primary")]]
    for row in proxies:
        rows.append([b(f"🗑 Remove #{row[0]}", f"own:p:rm:{row[0]}", style="danger")])
    if proxies:
        rows.append([b("🗑 Remove all", "own:p:all", style="danger")])
    rows.append([BACK])
    return rows


def cookies_menu(saved):
    rows = [
        [b("▶️ YouTube", "own:c:set:youtube", style="success"), b("🎵 Spotify", "own:c:set:spotify", style="success")],
        [b("🍎 Apple Music", "own:c:set:apple", style="success"), b("🌐 Other site", "own:c:other", style="primary")],
    ]
    tests = []
    yts = [sv for sv, *_ in saved if sv == "youtube" or sv.startswith("youtube:")]
    if yts:
        rows.insert(1, [b(f"➕ Add another YouTube ({len(yts)} saved)", "own:c:set:ytnew", style="success")])
        tests.append(b("🔍 Test YouTube", "own:c:test", style="primary"))
    if any(sv == "spotify" for sv, *_ in saved):
        tests.append(b("🔍 Test Spotify", "own:c:test:spotify", style="primary"))
    if tests:
        rows.append(tests)
    for service, *_ in saved:
        label = "youtube #1" if service == "youtube" else ("youtube #" + service.split(":")[1] if service.startswith("youtube:") else service)
        rows.append([b(f"🗑 Remove {label}"[:40], f"own:c:rm:{service}"[:64], style="danger")])
    if saved:
        rows.append([b("🗑 Remove all", "own:c:all", style="danger")])
    rows.append([BACK])
    return rows


def emoji_menu(ids: dict):
    rows, row = [], []
    for name in ui.EMOJI_NAMES:
        row.append(b(("✅ " if name in ids else "") + name, f"own:e:set:{name}", style="success" if name in ids else None))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if ids:
        rows.append([b("🗑 Clear all", "own:e:all", style="danger")])
    rows.append([BACK])
    return rows


def premium_menu():
    return [[b("➕ Grant premium", "own:pr:grant", style="success"), b("➖ Revoke", "own:pr:revoke", style="danger")], [BACK]]


def cancel_menu():
    return [[b("✖️ Cancel", "own:cancel", style="danger")]]


def confirm_broadcast(count: int):
    return [[b(f"✅ Send to {count} users", "own:bc:send", style="success"), b("✖️ Cancel", "own:cancel", style="danger")]]


def helpers_menu(helpers, can_add: bool):
    rows = []
    if can_add:
        rows.append([b("📱 Add by phone number", "own:h:phone", style="success"),
                     b("🔑 Add session string", "own:h:add", style="primary")])
    rows.append([b("🎨 Set names/bio/photo (slow & careful)", "own:h:brand", style="primary")])
    for h in helpers:
        if h.source == "db":
            rows.append([b(f"🗑 Remove helper #{h.index}", f"own:h:rm:{h.index}", style="danger")])
    rows.append([BACK])
    return rows


def backup_menu(enabled: bool):
    rows = [[b("💾 Back up now", "own:bk:now", style="success")]] if enabled else []
    rows.append([BACK])
    return rows
