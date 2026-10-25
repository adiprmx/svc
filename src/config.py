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
    try:
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip().upper()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return d


E = _env(os.path.join(BASE, ".env"))


def _clean(v):
    return v.strip() if isinstance(v, str) else v


def get(key, default=""):
    key = key.upper()
    for src in (_SECRET, E, os.environ):
        try:
            v = _clean(src.get(key))
        except Exception:
            continue
        if v not in (None, ""):
            return v
    return default


def geti(key, default=0):
    s = str(get(key, default)).strip()
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return default


def getf(key, default=0.0):
    try:
        return float(str(get(key, default)).strip())
    except Exception:
        return default


def getb(key, default=False):
    v = str(get(key, "1" if default else "0")).strip().lower()
    return v not in ("0", "false", "no", "off", "")


# --- kredensial ---
BOT_TOKEN = get("BOT_TOKEN")
OWNER_ID = geti("OWNER_ID", 0)
AUTO_OWNER = getb("AUTO_OWNER", True)
GITHUB_TOKEN = get("GITHUB_TOKEN")
GIST_ID = get("GIST_ID")

# --- http ---
UA = get("USER_AGENT", "Roblox/WinInet")
PROXY = get("PROXY", "")
HTTP_TIMEOUT = geti("HTTP_TIMEOUT", 20) or 20
MIN_DELAY = getf("MIN_DELAY", 1.1) or 1.1
MAX_DELAY = getf("MAX_DELAY", 4.0) or 4.0
WORKERS = geti("WORKERS", 2) or 2
ROTATE_UA = getb("ROTATE_UA", False)
FARM_THREADS = geti("FARM_THREADS", 4) or 4

# --- retry ---
MAX_ATTEMPTS = geti("MAX_ATTEMPTS", 3) or 3
RETRY_DELAY = getf("RETRY_DELAY", 20.0)
CAPTCHA_DELAY = getf("CAPTCHA_DELAY", 90.0)
MAX_CAPTCHA_TRIES = geti("MAX_CAPTCHA_TRIES", 5) or 5

# --- backup ---
BACKUP_EVERY = geti("BACKUP_EVERY", 600) or 600
BACKUP_FULL = getb("BACKUP_FULL", True)

# --- captcha / warm ---
CAPTCHA_MODE = (get("CAPTCHA_MODE", "auto") or "auto").lower()
CAPTCHA_ACTION_TYPE = get("CAPTCHA_ACTION_TYPE", "Login")
CAPTCHA_PUBLIC_KEY = get("CAPTCHA_PUBLIC_KEY", "")
KEYS_URL = get("KEYS_URL", "https://apis.rbxcdn.com/captcha/v1/metadata")
WARM_TIMEOUT = getf("WARM_TIMEOUT", 300.0)
WARM_RETRY = getf("WARM_RETRY", 600.0)
WARM_PAGE = get("WARM_PAGE", "https://adiprmx.github.io/svc/warm.html")
CAPTCHA_BREAKER_WINDOW = geti("CAPTCHA_BREAKER_WINDOW", 10) or 10
CAPTCHA_BREAKER_RATE = getf("CAPTCHA_BREAKER_RATE", 0.5)

# --- mode / shard ---
MODE = (os.environ.get("SVCMODE") or get("SVCMODE", "full") or "full").lower()
DURATION = geti("SVC_DURATION", 0)
SHARD = geti("SVC_SHARD", 0)
SHARDS = geti("SVC_SHARDS", 1) or 1
FORCE = getb("SVC_FORCE", False)
DOCTOR = getb("SVC_DOCTOR", True)

DB_PATH = os.path.join(DATA, "rbx.db")
PWFILE = os.path.join(DATA, "passwords.txt")
SEED_PWFILE = os.path.join(BASE, "data", "passwords.txt")
LOG_PATH = os.path.join(BASE, "x.log")
OWNER_FILE = os.path.join(DATA, "owner.txt")


def problems():
    out = []
    if not BOT_TOKEN:
        out.append("BOT_TOKEN kosong")
    elif ":" not in BOT_TOKEN:
        out.append("BOT_TOKEN formatnya aneh (harus ada ':')")
    if not AUTO_OWNER and not OWNER_ID:
        out.append("OWNER_ID 0 dan AUTO_OWNER mati -> bot gak bisa balas siapapun")
    return out


def describe():
    def mask(v):
        if not v:
            return "-"
        return v[:6] + "..." + v[-4:] if len(v) > 12 else v
    return ("python=%s mode=%s\nBASE=%s\nBOT_TOKEN=%s\nOWNER_ID=%s auto_owner=%s\n"
            "UA=%s workers=%d captcha=%s" % (
                os.sys.version.split()[0], MODE, BASE, mask(BOT_TOKEN),
                OWNER_ID or "(belum di-set)", AUTO_OWNER, UA, WORKERS, CAPTCHA_MODE))
