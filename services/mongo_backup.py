"""MongoDB snapshots of the bot's SQLite database (keys, proxies, cookies, helpers, settings, playlists, users).

SQLite stays the live database (fast, no network on every command). Every BACKUP_INTERVAL_MINUTES a consistent copy
is gzipped and stored in MongoDB; when the bot starts with no local database (new VPS, wiped volume) the latest
snapshot is restored automatically. Needs MONGO_URL in .env (a free Atlas M0 cluster is plenty).
"""
import asyncio
import gzip
import hashlib
import logging
import os
import sqlite3
import tempfile
import time

import config

log = logging.getLogger("backup")

CHUNK = 4 * 1024 * 1024
COLLECTION = "snapshots"
status = {"last_ok": None, "last_error": "", "size": 0, "restored": False}
_last_hash = ""


def enabled() -> bool:
    return bool(config.MONGO_URL)


def _client():
    from pymongo import AsyncMongoClient

    return AsyncMongoClient(config.MONGO_URL, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)


def _dump() -> bytes:
    """Consistent gzipped copy of the live database (safe while the bot is writing)."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with open(tmp, "rb") as f:
            return gzip.compress(f.read(), 6)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


async def backup_now(force: bool = False) -> str:
    """Returns a short result text. Skips when nothing changed since the last snapshot (unless forced)."""
    global _last_hash
    if not enabled():
        return "MongoDB is not configured (set MONGO_URL in .env)."
    if not os.path.exists(config.DB_PATH):
        return "No local database yet."
    client = _client()
    try:
        blob = await asyncio.to_thread(_dump)
        digest = hashlib.sha256(blob).hexdigest()
        if digest == _last_hash and not force:
            return "Unchanged since the last snapshot."
        col = client[config.MONGO_DB][COLLECTION]
        version = int(time.time())
        parts = [blob[i:i + CHUNK] for i in range(0, len(blob), CHUNK)] or [b""]
        for n, part in enumerate(parts):
            await col.replace_one({"_id": f"{version}:{n}"}, {"_id": f"{version}:{n}", "v": version, "n": n, "data": part},
                                  upsert=True)
        await col.replace_one({"_id": "meta"}, {"_id": "meta", "v": version, "parts": len(parts), "sha": digest,
                                                "size": len(blob), "at": version}, upsert=True)
        await col.delete_many({"v": {"$lt": version}})  # drop older snapshots
        _last_hash = digest
        status.update(last_ok=version, last_error="", size=len(blob))
        return f"Snapshot saved ({len(blob) / 1024:.0f} KB)."
    except Exception as e:
        status["last_error"] = type(e).__name__
        log.warning("backup failed: %s", e)
        return f"Backup failed ({type(e).__name__}). Check MONGO_URL and Atlas Network Access (allow this server's IP)."
    finally:
        await client.close()


async def restore_if_missing() -> str | None:
    """Called before the database is opened. Restores the newest snapshot only when there is no local database."""
    if not enabled():
        return None
    if os.path.exists(config.DB_PATH) and os.path.getsize(config.DB_PATH) > 0:
        return None
    client = _client()
    try:
        col = client[config.MONGO_DB][COLLECTION]
        meta = await col.find_one({"_id": "meta"})
        if not meta:
            return None
        chunks = [d async for d in col.find({"v": meta["v"]}).sort("n", 1) if "data" in d]
        blob = b"".join(d["data"] for d in chunks)
        if hashlib.sha256(blob).hexdigest() != meta["sha"]:
            log.error("snapshot checksum mismatch; not restoring")
            return "Snapshot in MongoDB is damaged; starting empty."
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        with open(config.DB_PATH, "wb") as f:
            f.write(gzip.decompress(blob))
        os.chmod(config.DB_PATH, 0o600)
        status["restored"] = True
        return f"Restored your data from the MongoDB snapshot of {time.strftime('%Y-%m-%d %H:%M', time.gmtime(meta['at']))} UTC."
    except Exception as e:
        log.warning("restore failed: %s", e)
        return f"Couldn't restore from MongoDB ({type(e).__name__}); starting empty."
    finally:
        await client.close()


def describe() -> str:
    if not enabled():
        return "💾 <b>Backup</b>\nMongoDB is <b>not configured</b>. Put <code>MONGO_URL=...</code> in .env and restart."
    when = (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(status["last_ok"])) if status["last_ok"] else "not yet")
    err = f"\n⚠️ Last error: {status['last_error']}" if status["last_error"] else ""
    return (f"💾 <b>MongoDB backup</b>\nEvery {config.BACKUP_INTERVAL_MINUTES} min · last snapshot: {when} "
            f"({status['size'] / 1024:.0f} KB){err}\nOn a fresh server the newest snapshot is restored automatically.")


async def _loop():
    await asyncio.sleep(60)
    while True:
        try:
            await backup_now()
        except Exception:
            log.exception("backup loop")
        await asyncio.sleep(max(5, config.BACKUP_INTERVAL_MINUTES) * 60)


def start():
    if enabled():
        return asyncio.get_event_loop().create_task(_loop())


if __name__ == "__main__":  # python -m services.mongo_backup [backup|restore]
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "backup"
    if cmd == "restore":
        if os.path.exists(config.DB_PATH):
            os.rename(config.DB_PATH, config.DB_PATH + ".old")
        print(asyncio.run(restore_if_missing()))
    else:
        print(asyncio.run(backup_now(force=True)))
