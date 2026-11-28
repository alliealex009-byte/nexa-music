import os

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    joined_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    admin_only INTEGER DEFAULT 1,
    loop INTEGER DEFAULT 0,
    volume INTEGER DEFAULT 100,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(user_id, name)
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    title TEXT,
    url TEXT,
    duration INTEGER
);
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT UNIQUE NOT NULL,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP,
    exhausted_until TEXT,
    invalid INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    fails INTEGER DEFAULT 0,
    latency_ms INTEGER,
    checked_at TEXT,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cookies (
    service TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS helper_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session TEXT NOT NULL UNIQUE,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auth_users (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS emoji_ids (
    name TEXT PRIMARY KEY,
    emoji_id TEXT NOT NULL
);
"""

# Settings added after the first release; existing databases get them via ALTER TABLE.
GROUP_COLUMNS = {
    "auto_pause": "INTEGER DEFAULT 1",
    "play_mode": "TEXT DEFAULT 'everyone'",
    "delete_commands": "INTEGER DEFAULT 0",
    "auto_delete": "INTEGER DEFAULT 0",
    "silent": "INTEGER DEFAULT 0",
    "language": "TEXT DEFAULT 'en'",
    "autoplay": "INTEGER DEFAULT 0",
    "idle_stop": "INTEGER DEFAULT 1",
    "lyrics": "INTEGER DEFAULT 0",
    "karaoke": "INTEGER DEFAULT 0",
    "welcome": "INTEGER DEFAULT 0",
}


async def init_db():
    folder = os.path.dirname(config.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(SCHEMA)
        cur = await db.execute("PRAGMA table_info(groups)")
        have = {row[1] for row in await cur.fetchall()}
        for column, decl in GROUP_COLUMNS.items():
            if column not in have:
                await db.execute(f"ALTER TABLE groups ADD COLUMN {column} {decl}")
        cur = await db.execute("PRAGMA table_info(helper_sessions)")
        if "proxy" not in {row[1] for row in await cur.fetchall()}:
            await db.execute("ALTER TABLE helper_sessions ADD COLUMN proxy TEXT")
        await db.commit()
    try:  # the DB holds API keys, proxy logins and cookies
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass


def connect():
    return aiosqlite.connect(config.DB_PATH)
