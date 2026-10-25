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
