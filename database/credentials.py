"""YouTube API keys, SOCKS5 proxies, cookies and premium-emoji ids (managed by the owner in DM)."""
from datetime import datetime, timezone

from database import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------- helper (assistant) sessions
async def add_helper_session(session: str, proxy: str | None = None) -> int | None:
    async with connect() as db:
        try:
            cur = await db.execute("INSERT INTO helper_sessions (session, proxy) VALUES (?, ?)", (session, proxy))
            await db.commit()
            return cur.lastrowid
        except Exception:  # duplicate
            return None


async def list_helper_sessions() -> list[tuple[int, str]]:
    async with connect() as db:
        cur = await db.execute("SELECT id, session FROM helper_sessions ORDER BY id")
        return await cur.fetchall()


async def list_helper_rows() -> list[tuple[int, str, str | None]]:
    async with connect() as db:
        cur = await db.execute("SELECT id, session, proxy FROM helper_sessions ORDER BY id")
        return await cur.fetchall()


async def remove_helper_session(row_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM helper_sessions WHERE id = ?", (row_id,))
        await db.commit()
        return cur.rowcount > 0


# ----------------------------------------------------------------- API keys
async def add_key(key: str) -> int | None:
    async with connect() as db:
        try:
            cur = await db.execute("INSERT INTO api_keys (api_key) VALUES (?)", (key,))
            await db.commit()
            return cur.lastrowid
        except Exception:  # duplicate
            return None


async def list_keys() -> list[tuple]:
    """[(id, api_key, exhausted_until | None, invalid)]"""
    async with connect() as db:
        cur = await db.execute("SELECT id, api_key, exhausted_until, invalid FROM api_keys ORDER BY id")
        return await cur.fetchall()


async def usable_keys() -> list[tuple[int, str]]:
    async with connect() as db:
        cur = await db.execute(
            "SELECT id, api_key FROM api_keys WHERE invalid = 0 "
            "AND (exhausted_until IS NULL OR exhausted_until <= ?) ORDER BY id",
            (_now(),),
        )
        return await cur.fetchall()


async def remove_key(key_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        await db.commit()
        return cur.rowcount > 0


async def clear_keys() -> int:
    async with connect() as db:
        cur = await db.execute("DELETE FROM api_keys")
        await db.commit()
        return cur.rowcount


async def mark_exhausted(key_id: int, until: datetime):
    async with connect() as db:
        await db.execute("UPDATE api_keys SET exhausted_until = ? WHERE id = ?", (until.isoformat(), key_id))
        await db.commit()


async def mark_invalid(key_id: int):
    async with connect() as db:
        await db.execute("UPDATE api_keys SET invalid = 1 WHERE id = ?", (key_id,))
        await db.commit()


# ----------------------------------------------------------------- proxies
async def add_proxy(url: str) -> int | None:
    async with connect() as db:
        try:
            cur = await db.execute("INSERT INTO proxies (url) VALUES (?)", (url,))
            await db.commit()
            return cur.lastrowid
        except Exception:  # duplicate
            return None


async def list_proxies() -> list[tuple]:
    """[(id, url, fails, latency_ms | None, checked_at | None)]"""
    async with connect() as db:
        cur = await db.execute("SELECT id, url, fails, latency_ms, checked_at FROM proxies ORDER BY id")
        return await cur.fetchall()


async def remove_proxy(proxy_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        await db.commit()
        return cur.rowcount > 0


async def clear_proxies() -> int:
    async with connect() as db:
        cur = await db.execute("DELETE FROM proxies")
        await db.commit()
        return cur.rowcount


async def record_proxy_ok(proxy_id: int, latency_ms: int):
    async with connect() as db:
        await db.execute(
            "UPDATE proxies SET fails = 0, latency_ms = ?, checked_at = ? WHERE id = ?",
            (latency_ms, _now(), proxy_id),
        )
        await db.commit()


async def record_proxy_fail(proxy_id: int) -> int:
    """Increment the failure counter and return the new value."""
    async with connect() as db:
        await db.execute(
            "UPDATE proxies SET fails = fails + 1, checked_at = ? WHERE id = ?", (_now(), proxy_id)
        )
        await db.commit()
        cur = await db.execute("SELECT fails FROM proxies WHERE id = ?", (proxy_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


# ----------------------------------------------------------------- cookies
async def set_cookies(service: str, content: str):
    async with connect() as db:
        await db.execute(
            "INSERT OR REPLACE INTO cookies (service, content, updated_at) VALUES (?, ?, ?)",
            (service, content, _now()),
        )
        await db.commit()


async def get_cookies(service: str) -> str | None:
    async with connect() as db:
        cur = await db.execute("SELECT content FROM cookies WHERE service = ?", (service,))
        row = await cur.fetchone()
        return row[0] if row else None


async def all_cookies() -> list[tuple[str, str, str]]:
    """[(service, content, updated_at)]"""
    async with connect() as db:
        cur = await db.execute("SELECT service, content, updated_at FROM cookies ORDER BY service")
        return await cur.fetchall()


async def remove_cookies(service: str) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM cookies WHERE service = ?", (service,))
        await db.commit()
        return cur.rowcount > 0


async def clear_cookies() -> int:
    async with connect() as db:
        cur = await db.execute("DELETE FROM cookies")
        await db.commit()
        return cur.rowcount


# ----------------------------------------------------------------- premium emoji ids
async def set_emoji(name: str, emoji_id: str):
    async with connect() as db:
        await db.execute("INSERT OR REPLACE INTO emoji_ids (name, emoji_id) VALUES (?, ?)", (name, emoji_id))
        await db.commit()


async def list_emojis() -> list[tuple[str, str]]:
    async with connect() as db:
        cur = await db.execute("SELECT name, emoji_id FROM emoji_ids ORDER BY name")
        return await cur.fetchall()


async def remove_emoji(name: str) -> bool:
    async with connect() as db:
        cur = await db.execute("DELETE FROM emoji_ids WHERE name = ?", (name,))
        await db.commit()
        return cur.rowcount > 0


async def clear_emojis() -> int:
    async with connect() as db:
        cur = await db.execute("DELETE FROM emoji_ids")
        await db.commit()
        return cur.rowcount


# ----------------------------------------------------------------- small key/value store
async def get_kv(key: str, default: str | None = None) -> str | None:
    async with connect() as db:
        cur = await db.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_kv(key: str, value: str):
    async with connect() as db:
        await db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        await db.commit()
