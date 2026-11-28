"""/ping for everyone: how fast the bot answers, how long it has been up and how the voice engine is doing."""
import asyncio
import inspect
import time

from pyrogram import Client, filters

import config

from services import botapi, cardimg, player, queue_manager, sysinfo, ui
from services.ui import b


def _quality(ms: float) -> str:
    return "🟢" if ms < 400 else "🟡" if ms < 1200 else "🔴"


async def _call_ping(helper) -> float | None:
    """Voice-call latency reported by py-tgcalls (None if this version doesn't expose it)."""
    try:
        value = getattr(helper.calls, "ping", None)
        if callable(value):
            value = value()
        if inspect.isawaitable(value):
            value = await asyncio.wait_for(value, 3)
        return float(value) if value is not None else None
    except Exception:
        return None


async def _mtproto_rtt(client) -> float | None:
    """Real round trip to Telegram's servers (MTProto ping), the fairest 'latency' number."""
    try:
        from pyrogram.raw.functions import Ping

        t = time.monotonic()
        await client.invoke(Ping(ping_id=int(t * 1000) & 0x7FFFFFFF))
        return (time.monotonic() - t) * 1000
    except Exception:
        return None


async def _api_rtt() -> float | None:
    try:
        t = time.monotonic()
        await botapi.call("getMe")
        return (time.monotonic() - t) * 1000
    except Exception:
        return None


@Client.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    t0 = time.monotonic()
    # everything at once: no "Pinging…" placeholder message, no sequential waits
    rtt, api_ms, *pings = await asyncio.gather(_mtproto_rtt(client), _api_rtt(), *[_call_ping(h) for h in player.helpers()])
    pings = [(h.index, p) for h, p in zip(player.helpers(), pings)]
    mid = None
    send_ms = rtt if rtt is not None else (api_ms if api_ms is not None else (time.monotonic() - t0) * 1000)
    voice = [f"#{i} {p:.0f} ms" for i, p in pings if p is not None]
    status = "ᴏɴʟɪɴᴇ" if send_ms < 1200 else "sʟᴏᴡ"
    lines = [
        f"<blockquote>🏓 <b>ᴘᴏɴɢ!</b> {_quality(send_ms)}</blockquote>",
        "<blockquote expandable>"
        f"<b>VERSION:</b> {config.VERSION}\n"
        f"<b>LATENCY:</b> {send_ms:.0f} ms" + (f" · API {api_ms:.0f} ms" if api_ms is not None and rtt is not None else "") + "\n"
        + (f"<b>VOICE:</b> {' · '.join(voice)}\n" if voice else "")
        + f"<b>UPTIME:</b> {sysinfo.uptime()}\n"
        f"<b>STATUS:</b> {status} · 🎧 {len(queue_manager.active_chats())} chat(s) · 🤖 {len(player.helpers())} helper(s)",
    ]
    if message.from_user and message.from_user.id == config.OWNER_ID:
        snap = sysinfo.snapshot()
        cpu = f"{snap['cpu']:.0f}%" if snap.get("cpu") is not None else "n/a"
        lines[-1] += f"\n<b>SERVER:</b> CPU {cpu} · RAM {snap['ram']}"
    lines[-1] += "</blockquote>"
    text = "\n".join(lines)
    row = [b("👑 OWNER", url=f"tg://user?id={config.OWNER_ID}", style="primary")]
    if config.SUPPORT_GROUP:
        row.append(b("💬 SUPPORT", url=f"https://t.me/{config.SUPPORT_GROUP}"))
    if config.UPDATES_CHANNEL:
        row.append(b("📢 UPDATES", url=f"https://t.me/{config.UPDATES_CHANNEL}"))
    rows = [row, [b("✖️ CLOSE", "close", style="danger")]]
    img = await cardimg.render(cardimg.render_ping, await cardimg.fetch(config.WELCOME_IMAGE), int(send_ms),
                               sysinfo.uptime())
    sent = await ui.send(message.chat.id, text, rows, photo_bytes=img, reply_to=message.id)
    if sent:
        if mid:
            await ui.delete(message.chat.id, mid)
    elif mid:
        await ui.edit(message.chat.id, mid, text, rows)
    else:
        await ui.reply(message, text, rows)


@Client.on_message(filters.command("debug"))
async def debug_cmd(client, message):
    """Owner only: the last playback errors (play/pause/leave failures) so problems are visible without the server logs."""
    if not message.from_user or message.from_user.id != config.OWNER_ID:
        return
    import time as _t

    from services import audio_provider

    rows = []
    for ts, chat, action, err in reversed(player.errors[-8:]):
        rows.append(f"• {int(_t.time() - ts)}s ago · <code>{chat}</code> · <b>{action}</b> · <code>{ui_esc(err)[:160]}</code>")
    helpers = ", ".join(f"#{h.index}" for h in player.helpers())
    text = ("🛠 <b>Playback debug</b>\n" + ("\n".join(rows) if rows else "No playback errors recorded. ✅")
            + f"\n\nHelpers: {helpers}\nActive chats: {len(queue_manager.active_chats())}")
    await ui.reply(message, text)


def ui_esc(v) -> str:
    from utils.text import esc

    return esc(v)
