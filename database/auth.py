"""Authorized users per chat (may use admin playback commands without being admins)."""
from database import connect


async def add(chat_id: int, user_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO auth_users (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def remove(chat_id: int, user_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "DELETE FROM auth_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def list_for(chat_id: int) -> list[int]:
    async with connect() as db:
        cur = await db.execute("SELECT user_id FROM auth_users WHERE chat_id = ? ORDER BY rowid", (chat_id,))
        return [r[0] for r in await cur.fetchall()]


async def is_authorized(chat_id: int, user_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "SELECT 1 FROM auth_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
        )
        return await cur.fetchone() is not None
