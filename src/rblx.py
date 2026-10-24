import random

import config, util

AUTH = "https://auth.roblox.com"

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


class Roblox:
    def __init__(self, ua=None, timeout=None, proxy=None):
        self.s = util.Session(ua or config.UA, timeout or config.HTTP_TIMEOUT,
                              proxy if proxy is not None else (config.PROXY or None))

    def reset(self, rotate=False):
        self.s.clear_cookies()
        if rotate:
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

    def login(self, username, password):
        if not self.s.csrf:
            self.csrf()
        sent = self.s.csrf
        body = {"ctype": "Username", "cvalue": username, "password": password}
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body)
        status, detail = classify(code, hdr, js, text)
        if status == "csrf" or (code == 403 and not sent and self.s.csrf):
            self.csrf()
            code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body)
            status, detail = classify(code, hdr, js, text)
        return status, detail, self.s.roblosecurity


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
