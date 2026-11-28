import logging
import os
from logging.handlers import RotatingFileHandler

import config


def setup_logging():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "bot.log"), maxBytes=5_000_000, backupCount=3
    )
    file.setFormatter(fmt)

    root.handlers = [console, file]
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
