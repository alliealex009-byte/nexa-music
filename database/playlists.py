from database import connect


async def create(user_id: int, name: str) -> bool:
    async with connect() as db:
        try:
            await db.execute("INSERT INTO playlists (user_id, name) VALUES (?, ?)", (user_id, name))
            await db.commit()
            return True
        except Exception:
            return False


async def list_for(user_id: int) -> list[tuple[int, str]]:
    async with connect() as db:
        cur = await db.execute("SELECT id, name FROM playlists WHERE user_id = ? ORDER BY id", (user_id,))
        return await cur.fetchall()


async def list_with_counts(user_id: int) -> list[tuple[int, str, int]]:
    async with connect() as db:
        cur = await db.execute(
            "SELECT p.id, p.name, COUNT(t.id) FROM playlists p "
            "LEFT JOIN playlist_tracks t ON t.playlist_id = p.id "
            "WHERE p.user_id = ? GROUP BY p.id ORDER BY p.id",
            (user_id,),
        )
        return await cur.fetchall()


async def find(user_id: int, name: str) -> tuple[int, str] | None:
    """Case-insensitive lookup of one of the user's playlists -> (id, real name)."""
    async with connect() as db:
        cur = await db.execute(
            "SELECT id, name FROM playlists WHERE user_id = ? AND lower(name) = lower(?)",
            (user_id, name.strip()),
        )
        return await cur.fetchone()


async def count(user_id: int) -> int:
    async with connect() as db:
        cur = await db.execute("SELECT COUNT(*) FROM playlists WHERE user_id = ?", (user_id,))
        return (await cur.fetchone())[0]


async def add_track(playlist_id: int, title: str, url: str, duration: int):
    async with connect() as db:
        await db.execute(
            "INSERT INTO playlist_tracks (playlist_id, title, url, duration) VALUES (?, ?, ?, ?)",
            (playlist_id, title, url, duration),
        )
        await db.commit()


async def tracks(playlist_id: int) -> list[tuple[str, str, int]]:
    async with connect() as db:
        cur = await db.execute(
            "SELECT title, url, duration FROM playlist_tracks WHERE playlist_id = ? ORDER BY id",
            (playlist_id,),
        )
        return await cur.fetchall()


async def remove_track_at(playlist_id: int, index: int) -> tuple[str, str] | None:
    """Remove the track at 1-based `index`; returns (title, url) or None if out of range."""
    async with connect() as db:
        cur = await db.execute(
            "SELECT id, title, url FROM playlist_tracks WHERE playlist_id = ? ORDER BY id", (playlist_id,)
        )
        rows = await cur.fetchall()
        if not 1 <= index <= len(rows):
            return None
        row_id, title, url = rows[index - 1]
        await db.execute("DELETE FROM playlist_tracks WHERE id = ?", (row_id,))
        await db.commit()
        return title, url


async def owner_of(playlist_id: int) -> int | None:
    async with connect() as db:
        cur = await db.execute("SELECT user_id FROM playlists WHERE id = ?", (playlist_id,))
        row = await cur.fetchone()
        return row[0] if row else None


async def delete(playlist_id: int):
    async with connect() as db:
        await db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        await db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        await db.commit()
