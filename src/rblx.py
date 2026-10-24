import base64, json, random

import config, util

AUTH = "https://auth.roblox.com"
CHALLENGE = "https://apis.roblox.com/challenge/v1/continue"

UAS = [
    "Roblox/WinInet",
    "Roblox/2.616.551 (Android; Android 12; SM-G991B)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]

CSRF_PROBES = [
    ("POST", AUTH + "/v2/login"),
    ("POST", AUTH + "/v2/logout"),
    ("GET", "https://www.roblox.com/home"),
]

BROWSER_HDR = {
    "Origin": "https://www.roblox.com",
    "Referer": "https://www.roblox.com/",
}


def parse_challenge(hdr):
    """Ambil challenge dari header 403. Tahan banting ke 2 bentuk payload."""
    cid = hdr.get("rblx-challenge-id")
    ctype = hdr.get("rblx-challenge-type") or "captcha"
    raw = hdr.get("rblx-challenge-metadata")
    inner = {}
    if raw:
        try:
            dec = json.loads(base64.b64decode(raw).decode("utf-8", "replace"))
            if isinstance(dec, dict):
                nested = dec.get("challengeMetadata")
                if isinstance(nested, dict):
                    inner = nested
                    cid = dec.get("challengeId") or cid
                    ctype = dec.get("challengeType") or ctype
                else:
                    inner = dec
        except Exception:
            inner = {}
    return {"id": cid, "type": ctype, "inner": inner, "raw": raw, "token": None}


class Roblox:
    def __init__(self, ua=None, timeout=None, proxy=None):
        self.s = util.Session(ua or config.UA, timeout or config.HTTP_TIMEOUT,
                              proxy if proxy is not None else (config.PROXY or None))
        self.s.extra.update(BROWSER_HDR)
        self.challenge = None

    def reset(self, rotate=False):
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
        sent = self.s.csrf
        body = {"ctype": self._ctype(username), "cvalue": username, "password": password}
        extra = dict(challenge_headers or {}) or None
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body, headers=extra)
        status, detail = classify(code, hdr, js, text)
        if status == "captcha":
            self.challenge = parse_challenge(hdr)
        elif status == "csrf" or (code == 403 and not sent and self.s.csrf):
            self.csrf()
            code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body)
            status, detail = classify(code, hdr, js, text)
            if status == "captcha":
                self.challenge = parse_challenge(hdr)
        return status, detail, self.s.roblosecurity

    def continue_challenge(self, token, challenge=None):
        """Kirim token hasil solve ke challenge/v1/continue."""
        ch = challenge or self.challenge
        if not ch:
            return False
        ch["token"] = token
        inner = dict(ch.get("inner") or {})
        inner["solvedCaptchaToken"] = token
        payload = {
            "challengeId": ch.get("id"),
            "challengeMetadata": json.dumps(inner),
            "challengeType": ch.get("type") or "captcha",
        }
        code, hdr, text, js = self.s.request("POST", CHALLENGE, payload)
        return code == 200

    def challenge_headers(self, challenge=None):
        ch = challenge or self.challenge
        if not ch or not ch.get("token"):
            return None
        inner = dict(ch.get("inner") or {})
        inner["solvedCaptchaToken"] = ch["token"]
        return {
            "Rblx-Challenge-Id": ch.get("id"),
            "Rblx-Challenge-Metadata": base64.b64encode(
                json.dumps(inner).encode()).decode(),
            "Rblx-Challenge-Type": ch.get("type") or "captcha",
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
        if hdr.get("rblx-challenge-id") or ctype == "captcha" or "captcha" in low or "robot" in low:
            return "captcha", msg or ctype
        if ctype == "twostepverification" or "two step" in low or "two-step" in low:
            return "2fa", msg
        if "token validation" in low:
            return "csrf", msg
        if "incorrect" in low or "invalid" in low:
            return "invalid", msg
        return "denied", "%s | %s" % (code, msg or (text or "")[:80])
    return "error", "%s %s" % (code, (text or "")[:200])
