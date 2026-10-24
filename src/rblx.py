import config, util

AUTH = "https://auth.roblox.com"


class Roblox:
    def __init__(self, ua=None, timeout=None):
        self.s = util.Session(ua or config.UA, timeout or config.HTTP_TIMEOUT)

    def csrf(self):
        self.s.request("GET", AUTH + "/v2/login")
        return self.s.csrf

    def login(self, username, password):
        if not self.s.csrf:
            self.csrf()
        body = {"ctype": "Username", "cvalue": username, "password": password}
        code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body)
        status, detail = classify(code, hdr, js, text)
        if status == "csrf":
            self.csrf()
            code, hdr, text, js = self.s.request("POST", AUTH + "/v2/login", body)
            status, detail = classify(code, hdr, js, text)
        return status, detail, self.s.roblosecurity


def classify(code, hdr, js, text):
    if code == 200:
        return "hit", "ok"
    if code == 429:
        return "ratelimited", hdr.get("Retry-After") or ""
    if code == 403:
        ctype = (hdr.get("rblx-challenge-type") or "").lower()
        msg = ""
        if isinstance(js, dict):
            errs = js.get("errors") or []
            if errs and isinstance(errs[0], dict):
                msg = errs[0].get("message") or ""
        low = msg.lower()
        if "token validation" in low:
            return "csrf", msg
        if ctype == "twostepverification" or "two step" in low or "two-step" in low:
            return "2fa", msg
        if hdr.get("rblx-challenge-id") or ctype == "captcha" or "captcha" in low or "robot" in low:
            return "captcha", msg
        if "incorrect" in low or "invalid" in low:
            return "invalid", msg
        return "denied", msg or "HTTP403"
    return "error", (text or "")[:200]
