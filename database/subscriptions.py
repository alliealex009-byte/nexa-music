from datetime import datetime, timedelta

from database import connect


async def grant(user_id: int, days: int):
    async with connect() as db:
        cur = await db.execute("SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        base = datetime.utcnow()
        if row:
            current = datetime.fromisoformat(row[0])
            if current > base:
                base = current
        expires = base + timedelta(days=days)
        await db.execute(
            "INSERT OR REPLACE INTO subscriptions (user_id, expires_at) VALUES (?, ?)",
            (user_id, expires.isoformat()),
        )
        await db.commit()


async def revoke(user_id: int):
    async with connect() as db:
        await db.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
        await db.commit()


async def expiry(user_id: int) -> datetime | None:
    async with connect() as db:
        cur = await db.execute("SELECT expires_at FROM subscriptions WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
    if not row:
        return None
    exp = datetime.fromisoformat(row[0])
    return exp if exp > datetime.utcnow() else None


async def is_premium(user_id: int) -> bool:
    return await expiry(user_id) is not None
