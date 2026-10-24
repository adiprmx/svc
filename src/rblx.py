import base64, json, random, time

import config, util

AUTH = "https://auth.roblox.com"
APIS = "https://apis.roblox.com"
CHALLENGE = APIS + "/challenge/v1/continue"
KEY_URL = "https://apis.rbxcdn.com/captcha/v1/metadata"

# fallback kalau CDN gak kebaca
LOGIN_KEY = "476068BF-9607-4799-B53D-966BE98E2B81"

UAS = [
    "Roblox/WinInet",
    "Roblox/2.616.551 (Android; Android 12; SM-G991B)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

CSRF_PROBES = [
    ("POST", AUTH + "/v2/login"),
    ("POST", AUTH + "/v2/logout"),
]

BROWSER_HDR = {
    "Origin": "https://www.roblox.com",
    "Referer": "https://www.roblox.com/",
}

_keys_cache = {"ts": 0.0, "keys": {}}


def public_key(kind="ACTION_TYPE_WEB_LOGIN"):
    if config.CAPTCHA_PUBLIC_KEY:
        return config.CAPTCHA_PUBLIC_KEY
    if _keys_cache["keys"] and time.time() - _keys_cache["ts"] < 3600:
        return _keys_cache["keys"].get(kind) or LOGIN_KEY
    try:
        s = util.Session("Roblox/WinInet", 10)
        code, hdr, text, js = s.request("GET", KEY_URL)
        if code == 200 and isinstance(js, dict):
            _keys_cache["keys"] = js.get("funCaptchaPublicKeys") or {}
            _keys_cache["ts"] = time.time()
    except Exception:
        pass
    return _keys_cache["keys"].get(kind) or LOGIN_KEY


def _b64json(raw):
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8", "replace"))
    except Exception:
        return None


def parse_challenge(hdr):
    """Tahan banting: metadata bisa dict ATAU string JSON bersarang."""
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
    blob = meta.get("dataExchangeBlob") or meta.get("blob") or ""
    return {"id": cid, "type": ctype, "meta": meta, "blob": blob,
            "public_key": meta.get("publicKey") or "", "raw": raw, "token": None}


def solve_metadata(ch, token):
    """Metadata yang dipakai buat continue + retry: asli + captchaToken."""
    meta = dict(ch.get("meta") or {})
    meta["captchaToken"] = token
    if ch.get("type") == "captcha":
        meta.setdefault("actionType", config.CAPTCHA_ACTION_TYPE)
    return meta


class Roblox:
    def __init__(self, ua=None, timeout=None, proxy=None):
        self.s = util.Session(ua or config.UA, timeout or config.HTTP_TIMEOUT,
                              proxy if proxy is not None else (config.PROXY or None))
        self.s.extra.update(BROWSER_HDR)
        self.challenge = None

    def reset(self, rotate=False, soft=False):
        if soft:
            self.s.drop_cookie(".ROBLOSECURITY")
        else:
            self.s.clear_cookies()
        self.challenge = None
        if rotate and config.ROTATE_UA:
            self.s.ua = random.choice(UAS)

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
        if status == "captcha":
            self.challenge = parse_challenge(hdr)
        elif status == "2fa":
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
        """Selesain 2FA: retry login + twoStepVerificationCode + challenge header."""
        ch = challenge or self.challenge
        if not self.s.csrf:
            self.csrf()
        body = {"ctype": self._ctype(username), "cvalue": username,
                "password": password, "twoStepVerificationCode": code2}
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body,
                                             headers=self.challenge_headers(ch))
        status, detail = classify(code, hdr, js, text)
        return status, detail, self.s.roblosecurity

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
        if not ch or not ch.get("id"):
            return None
        if not ch.get("token"):
            return None
        meta = ch.get("meta_solved") or solve_metadata(ch, ch["token"])
        return {
            "Rblx-Challenge-Id": ch.get("id"),
            "Rblx-Challenge-Type": ch.get("type") or "captcha",
            "Rblx-Challenge-Metadata": base64.b64encode(
                json.dumps(meta).encode()).decode(),
        }


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
        return "denied", "%s | %s" % (code, msg or (text or "")[:80])
    return "error", "%s %s" % (code, (text or "")[:200])
