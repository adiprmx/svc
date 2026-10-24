import os

BASE = os.environ.get("SVCHOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, ".d")
os.makedirs(DATA, exist_ok=True)

try:
    from _secret import _SECRET
except Exception:
    _SECRET = {}


def _env(path):
    d = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


E = _env(os.path.join(BASE, ".env"))


def get(key, default=""):
    v = _SECRET.get(key) or E.get(key) or os.environ.get(key)
    return v if v not in (None, "") else default


def geti(key, default=0):
    try:
        return int(str(get(key, default)).strip() or default)
    except Exception:
        return default


def getf(key, default=0.0):
    try:
        return float(str(get(key, default)).strip() or default)
    except Exception:
        return default


def getb(key, default=False):
    return str(get(key, "1" if default else "0")).strip().lower() not in ("0", "false", "no", "off", "")


BOT_TOKEN = get("BOT_TOKEN")
OWNER_ID = geti("OWNER_ID", 0)
GITHUB_TOKEN = get("GITHUB_TOKEN")
GIST_ID = get("GIST_ID")

UA = get("USER_AGENT", "Roblox/WinInet")
PROXY = get("PROXY", "")

HTTP_TIMEOUT = geti("HTTP_TIMEOUT", 20) or 20
MIN_DELAY = getf("MIN_DELAY", 1.1) or 1.1
MAX_DELAY = getf("MAX_DELAY", 4.0) or 4.0
WORKERS = geti("WORKERS", 2) or 2

MAX_ATTEMPTS = geti("MAX_ATTEMPTS", 3) or 3
RETRY_DELAY = getf("RETRY_DELAY", 20.0)
CAPTCHA_DELAY = getf("CAPTCHA_DELAY", 90.0)

BACKUP_EVERY = geti("BACKUP_EVERY", 600) or 600
BACKUP_FULL = str(get("BACKUP_FULL", "1")).strip() not in ("0", "false", "False")

# --- captcha / warm ---
CAPTCHA_ACTION_TYPE = get("CAPTCHA_ACTION_TYPE", "Login")
CAPTCHA_PUBLIC_KEY = get("CAPTCHA_PUBLIC_KEY", "")   # kosong = auto dari CDN
KEYS_URL = get("KEYS_URL", "https://apis.rbxcdn.com/captcha/v1/metadata")
CAPTCHA_MODE = (get("CAPTCHA_MODE", "auto") or "auto").lower()
WARM_TIMEOUT = getf("WARM_TIMEOUT", 300.0)
WARM_RETRY = getf("WARM_RETRY", 600.0)
WARM_PAGE = get("WARM_PAGE", "https://adiprmx.github.io/svc/warm.html")
CAPTCHA_BREAKER_WINDOW = geti("CAPTCHA_BREAKER_WINDOW", 10) or 10
CAPTCHA_BREAKER_RATE = getf("CAPTCHA_BREAKER_RATE", 0.5)
MAX_CAPTCHA_TRIES = geti("MAX_CAPTCHA_TRIES", 5) or 5

# --- tuning ---
ROTATE_UA = getb("ROTATE_UA", False)
FARM_THREADS = geti("FARM_THREADS", 4) or 4

# --- sharding (buat multi runner) ---
SHARD = geti("SVC_SHARD", 0)
SHARDS = geti("SVC_SHARDS", 1) or 1

DB_PATH = os.path.join(DATA, "rbx.db")
PWFILE = os.path.join(DATA, "passwords.txt")
LOG_PATH = os.path.join(BASE, "x.log")
