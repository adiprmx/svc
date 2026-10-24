import gzip, http.cookiejar, json, urllib.error, urllib.request


class Session:
    def __init__(self, ua, timeout=20):
        self.ua, self.timeout = ua, timeout
        self.csrf = None
        self.extra = {}
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def cookie(self, name):
        for c in self.jar:
            if c.name == name:
                return c.value
        return None

    @property
    def roblosecurity(self):
        return self.cookie(".ROBLOSECURITY")

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
            return 0, {}, "", {"error": repr(e)}

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
