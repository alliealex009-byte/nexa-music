from database import connect


async def add_user(user_id: int, first_name: str):
    async with connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)",
            (user_id, first_name),
        )
        await db.commit()


async def count_users() -> int:
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]


async def all_user_ids() -> list[int]:
    async with connect() as db:
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]
