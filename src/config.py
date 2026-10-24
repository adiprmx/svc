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
    v = _SECRET.get(key) or E.get(key)
    return v if v not in (None, "") else default


BOT_TOKEN = get("BOT_TOKEN")
OWNER_ID = int(get("OWNER_ID", "0") or 0)
GITHUB_TOKEN = get("GITHUB_TOKEN")
GIST_ID = get("GIST_ID")

UA = get("USER_AGENT", "Roblox/WinInet")
HTTP_TIMEOUT = int(get("HTTP_TIMEOUT", "20") or 20)
MIN_DELAY = float(get("MIN_DELAY", "1.1") or 1.1)
MAX_DELAY = float(get("MAX_DELAY", "4.0") or 4.0)
WORKERS = int(get("WORKERS", "2") or 2)
MAX_RETRY = int(get("MAX_RETRY", "4") or 4)

DB_PATH = os.path.join(DATA, "rbx.db")
PWFILE = os.path.join(DATA, "passwords.txt")
LOG_PATH = os.path.join(BASE, "x.log")
