from pyrogram import Client, filters

from database import groups as groups_db
from pyrogram.enums import ChatType
from services import lyrics, queue_manager, ui
from utils import guards
from utils.text import chunk, esc


async def send_lyrics(chat_id: int, query: str, reply_to: int | None = None):
    progress = await ui.send(chat_id, "🎤 Looking for lyrics…", reply_to=reply_to)
    cur = queue_manager.current(chat_id)
    found = await lyrics.find(query, cur.duration if cur and cur.title == query else None)
    if progress:
        await ui.delete(chat_id, progress)
    if not found:
        return await ui.send(chat_id, f"❌ No lyrics found for <b>{esc(lyrics.clean_title(query))}</b>.", reply_to=reply_to)
    heading, text = found
    parts = chunk(esc(text), 3500)
    for i, part in enumerate(parts[:6]):
        head = f"🎤 <b>{esc(heading)}</b>\n" if i == 0 else ""
        await ui.send(chat_id, head + f"<blockquote expandable>{part}</blockquote>", reply_to=reply_to if i == 0 else None)
    if len(parts) > 6:
        await ui.send(chat_id, "…lyrics truncated.")


@Client.on_message(filters.command(guards.with_silent(guards.LYRICS)))
async def lyrics_cmd(client, message):
    if message.chat.type != ChatType.PRIVATE and not (await groups_db.get_settings(message.chat.id))["lyrics"]:
        return await ui.reply(message, "🎤 Lyrics are turned off in this group. An admin can enable them in /settings.")
    query = guards.query_of(message)
    if not query:
        cur = queue_manager.current(message.chat.id)
        query = cur.title if cur else ""
    if not query:
        return await ui.reply(message, "Usage: <code>/lyrics song name</code> (or use it while a song is playing)")
    await send_lyrics(message.chat.id, query, message.id)
