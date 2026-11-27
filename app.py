import asyncio
import logging

from pyrogram import Client, idle
from pytgcalls import PyTgCalls

import config
from database import init_db
from services import audio_provider, botapi, logchat, player, proxy_manager, ui, vc_monitor
from services.recovery import start_watchdog
from utils.logging_config import setup_logging

import os

os.makedirs(config.DATA_DIR, exist_ok=True)
setup_logging()
log = logging.getLogger("nexa")

bot = Client(
    "nexa_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    plugins=dict(root="handlers"),
    workdir=config.DATA_DIR,
)

assistant = Client(
    "nexa_assistant",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    session_string=config.SESSION_STRING,
    in_memory=True,
)

calls = PyTgCalls(assistant)


async def notify_owner(text: str, rows=None):
    if config.OWNER_ID:
        return await ui.send(config.OWNER_ID, text, rows, sticky=True)


async def announce_start(username: str):
    """Tell the owner the bot is up. If this fails, OWNER_ID is probably wrong (or the owner never pressed Start)."""
    if config.OWNER_ID in (0, 123456789):
        log.warning("OWNER_ID is not set (it is %s). Owner commands will not work: send /id to the bot and put that "
                    "number in .env as OWNER_ID.", config.OWNER_ID)
    mid = await notify_owner(
        f"✅ <b>{config.BOT_NAME} is online</b> (@{username})\nOpen the owner panel to add cookies, proxies and API keys.",
        [[ui.b("🛠 Owner Panel", "own:home", style="primary")]],
    )
    if not mid:
        log.warning("Could not message OWNER_ID=%s. Open @%s, press Start, and check OWNER_ID in .env.",
                    config.OWNER_ID, username)


async def main():
    await init_db()
    await logchat.load()
    await ui.load_emojis()

    await bot.start()
    await assistant.start()
    await calls.start()

    me = await bot.get_me()
    ui.setup(bot, me.username or "")
    player.setup(bot, assistant, calls)
    await player.assistant_info()

    audio_provider.alert_hook = notify_owner
    proxy_manager.start(notify=notify_owner)
    vc_monitor.start()
    start_watchdog(bot, calls)
    asyncio.get_event_loop().create_task(audio_provider.purge_loop(player.sources_in_use))
    audio_provider.purge_cache()

    log.info("Bot started as @%s", me.username)
    await announce_start(me.username or "")
    await idle()

    await botapi.close()
    await bot.stop()
    await assistant.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
