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

DB_PATH = os.path.join(DATA, "rbx.db")
PWFILE = os.path.join(DATA, "passwords.txt")
LOG_PATH = os.path.join(BASE, "x.log")
