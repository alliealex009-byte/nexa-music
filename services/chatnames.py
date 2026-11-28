"""Group names for log lines: turns "... in -1004463022881" into "... in Chugli (-1004463022881)"."""
import logging
import re

names: dict[int, str] = {}
_ID = re.compile(r"(?<![\w(])(-100\d{6,})(?![\w)])")


def remember(chat_id: int, title: str | None):
    if title:
        names[chat_id] = title


async def load():
    from database.db import connect

    try:
        async with connect() as db:
            cur = await db.execute("SELECT chat_id, title FROM groups WHERE title != ''")
            for chat_id, title in await cur.fetchall():
                names[chat_id] = title
    except Exception:
        pass


class NameFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if _ID.search(msg):
                record.msg = _ID.sub(lambda m: f"{names[int(m.group(1))]} ({m.group(1)})" if int(m.group(1)) in names
                                     else m.group(1), msg)
                record.args = ()
        except Exception:
            pass
        return True
