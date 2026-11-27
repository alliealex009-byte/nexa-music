import asyncio
import logging

from pyrogram import Client, idle
from pytgcalls import PyTgCalls

import config
from database import init_db
from services import audio_provider, botapi, commands_menu, helpers, logchat, mongo_backup, player, proxy_manager, ui, vc_monitor
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


async def announce_start(username: str, problems: list[str] | None = None):
    """Tell the owner the bot is up. If this fails, OWNER_ID is probably wrong (or the owner never pressed Start)."""
    if config.OWNER_ID in (0, 123456789):
        log.warning("OWNER_ID is not set (it is %s). Owner commands will not work: send /id to the bot and put that "
                    "number in .env as OWNER_ID.", config.OWNER_ID)
    mid = await notify_owner(
        f"✅ <b>{config.BOT_NAME} is online</b> (@{username}) · {len(player.helpers())} helper(s)\n"
        "Open the owner panel to add cookies, proxies, API keys and helpers."
        + ("".join(f"\n⚠️ {p}" for p in (problems or []))),
        [[ui.b("🛠 Owner Panel", "own:home", style="primary")]],
    )
    if not mid:
        log.warning("Could not message OWNER_ID=%s. Open @%s, press Start, and check OWNER_ID in .env.",
                    config.OWNER_ID, username)


async def main():
    restored = await mongo_backup.restore_if_missing()  # new server / wiped data folder: bring the data back first
    if restored:
        log.info(restored)
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
    problems = await helpers.start_extra()
    branding = await helpers.brand_all()
    for line in branding:
        log.info("helper branding: %s", line)

    await commands_menu.register()
    audio_provider.alert_hook = notify_owner
    proxy_manager.start(notify=notify_owner)
    vc_monitor.start()
    mongo_backup.start()
    start_watchdog(bot)
    asyncio.get_event_loop().create_task(audio_provider.purge_loop(player.sources_in_use))
    audio_provider.purge_cache()

    log.info("Bot started as @%s", me.username)
    await announce_start(me.username or "", problems)
    await idle()

    await botapi.close()
    await bot.stop()
    for h in player.helpers():
        await h.client.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
