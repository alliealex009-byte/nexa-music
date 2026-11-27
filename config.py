import os
from dotenv import load_dotenv

load_dotenv()


def _str(name: str, default: str = "") -> str:
    """Env string; a value that is really a trailing comment ("# ...") counts as empty."""
    value = os.getenv(name, default).strip()
    return "" if value.startswith("#") else value


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")  # assistant userbot (joins voice chats)

OWNER_ID = _int("OWNER_ID")
BOT_NAME = os.getenv("BOT_NAME", "RIA Music")
SUPPORT_GROUP = _str("SUPPORT_GROUP").lstrip("@")  # empty = hide the Support button
UPDATES_CHANNEL = _str("UPDATES_CHANNEL").lstrip("@")  # empty = hide the Updates button
DEFAULT_BANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "welcome.jpg")
WELCOME_IMAGE = _str("WELCOME_IMAGE") or (DEFAULT_BANNER if os.path.exists(DEFAULT_BANNER) else "")  # URL, file_id or local path

DB_PATH = os.getenv("DB_PATH", "data/nexa.db")
DATA_DIR = os.getenv("DATA_DIR", "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOG_DIR = os.getenv("LOG_DIR", "logs")

BOT_API_BASE = os.getenv("BOT_API_BASE", "https://api.telegram.org").rstrip("/")

# --- JioSaavn (unofficial API; point this at your own deployment for reliability)
# One or more hosts, comma-separated; they are tried in order and the last working one is preferred.
SAAVN_API_BASES = [b.strip().rstrip("/") for b in os.getenv("SAAVN_API_BASE", "https://saavn.sumit.co/api,https://saavn.dev/api").split(",") if b.strip()]
SAAVN_API_BASE = SAAVN_API_BASES[0] if SAAVN_API_BASES else ""
SAAVN_API_STYLE = os.getenv("SAAVN_API_STYLE", "dev").lower()  # dev | legacy
SAAVN_FALLBACK = _bool("SAAVN_FALLBACK", True)  # try JioSaavn when YouTube fails

# --- Lyrics (community database, no key needed)
LYRICS_API_BASE = os.getenv("LYRICS_API_BASE", "https://lrclib.net/api").rstrip("/")

# --- Proxies (SOCKS5 only; managed by the owner in DM)
PROXY_CHECK_INTERVAL = _int("PROXY_CHECK_INTERVAL", 300)  # seconds
PROXY_TIMEOUT = _int("PROXY_TIMEOUT", 10)
PROXY_MAX_FAILS = _int("PROXY_MAX_FAILS", 2)  # consecutive failed checks before auto-removal
PROXY_TEST_URL = os.getenv("PROXY_TEST_URL", "https://www.youtube.com/generate_204")

# --- Voice chat presence: pause when empty, leave when empty for a while (saves the VPS)
VC_CHECK_INTERVAL = _int("VC_CHECK_INTERVAL", 10)  # seconds
VC_EMPTY_CHECKS = _int("VC_EMPTY_CHECKS", 2)  # consecutive empty checks before pausing
VC_IDLE_STOP_SECONDS = _int("VC_IDLE_STOP_SECONDS", 300)  # empty this long -> stop and leave

# --- Audio cache and limits
MAX_DOWNLOAD_SECONDS = _int("MAX_DOWNLOAD_SECONDS", 3 * 3600)
CACHE_MAX_AGE = _int("CACHE_MAX_AGE", 6 * 3600)
MAX_TG_FILE_MB = _int("MAX_TG_FILE_MB", 200)
ENABLE_VPLAY = _bool("ENABLE_VPLAY", True)
VIDEO_MAX_HEIGHT = _int("VIDEO_MAX_HEIGHT", 480)  # keep video light on the VPS

MAX_QUEUE = _int("MAX_QUEUE", 50)
MAX_PLAYLIST_IMPORT = _int("MAX_PLAYLIST_IMPORT", 25)  # songs taken from a playlist/album link
MIX_SIZE = _int("MIX_SIZE", 10)
AUTO_JOIN_ASSISTANT = _bool("AUTO_JOIN_ASSISTANT", True)

TAGALL_PER_MESSAGE = _int("TAGALL_PER_MESSAGE", 5)
TAGALL_DELAY = float(os.getenv("TAGALL_DELAY", "2.5"))
TAGALL_MAX = _int("TAGALL_MAX", 5000)

FREE_PLAYLIST_LIMIT = _int("FREE_PLAYLIST_LIMIT", 3)
PREMIUM_PLAYLIST_LIMIT = _int("PREMIUM_PLAYLIST_LIMIT", 50)

# Where /logger sends play/error logs (defaults to the owner's DM)
LOG_CHAT_ID = _int("LOG_CHAT_ID", 0)

# Coloured inline buttons (Bot API `style`). Set false to use Telegram's default look.
BUTTON_STYLES = _bool("BUTTON_STYLES", True)
