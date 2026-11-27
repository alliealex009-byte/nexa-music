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
    no_updates=True,
    in_memory=True,
)

calls = PyTgCalls(assistant)


async def notify_owner(text: str):
    if config.OWNER_ID:
        await ui.send(config.OWNER_ID, text, sticky=True)


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

    proxy_manager.start(notify=notify_owner)
    vc_monitor.start()
    start_watchdog(bot, calls)
    asyncio.get_event_loop().create_task(audio_provider.purge_loop(player.sources_in_use))
    audio_provider.purge_cache()

    log.info("Bot started as @%s", me.username)
    await idle()

    await botapi.close()
    await bot.stop()
    await assistant.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
