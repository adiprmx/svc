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
