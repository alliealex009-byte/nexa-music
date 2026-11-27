"""/ping for everyone: how fast the bot answers, how long it has been up and how the voice engine is doing."""
import inspect
import time

from pyrogram import Client, filters

import config
from services import botapi, player, queue_manager, sysinfo, ui


def _quality(ms: float) -> str:
    return "🟢" if ms < 400 else "🟡" if ms < 1200 else "🔴"


async def _call_ping(helper) -> float | None:
    """Voice-call latency reported by py-tgcalls (None if this version doesn't expose it)."""
    try:
        value = getattr(helper.calls, "ping", None)
        if callable(value):
            value = value()
        if inspect.isawaitable(value):
            value = await value
        return float(value) if value is not None else None
    except Exception:
        return None


@Client.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    t0 = time.monotonic()
    mid = await ui.reply(message, "🏓 Pinging…")
    send_ms = (time.monotonic() - t0) * 1000
    api_ms = None
    try:
        t1 = time.monotonic()
        await botapi.call("getMe")
        api_ms = (time.monotonic() - t1) * 1000
    except Exception:
        pass
    lines = [f"🏓 <b>Pong!</b> {_quality(send_ms)} <b>{send_ms:.0f} ms</b>"]
    if api_ms is not None:
        lines.append(f"🌐 Telegram API: <b>{api_ms:.0f} ms</b>")
    pings = [(h.index, await _call_ping(h)) for h in player.helpers()]
    shown = [f"#{i} {p:.0f} ms" for i, p in pings if p is not None]
    if shown:
        lines.append("🎙 Voice engine: " + " · ".join(shown))
    lines.append(f"⏱ Uptime: <b>{sysinfo.uptime()}</b>")
    lines.append(f"🎧 Playing in <b>{len(queue_manager.active_chats())}</b> chat(s) · 🤖 {len(player.helpers())} helper(s)")
    if message.from_user and message.from_user.id == config.OWNER_ID:
        snap = sysinfo.snapshot()
        cpu = f"{snap['cpu']:.0f}%" if snap.get("cpu") is not None else "n/a"
        lines.append(f"🖥 CPU {cpu} · RAM {snap['ram']} · Disk {snap['disk']}")
    text = "\n".join(lines)
    if mid:
        await ui.edit(message.chat.id, mid, text)
    else:
        await ui.reply(message, text)
