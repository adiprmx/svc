import time

import config, store, util

GATE = 0.4


def run(start, count, stop, progress=None):
    s = util.Session(config.UA, config.HTTP_TIMEOUT, config.PROXY or None)
    got = 0
    for uid in range(start, start + count):
        if stop.is_set():
            break
        try:
            code, hdr, text, js = s.request(
                "GET", "https://users.roblox.com/v1/users/%d" % uid)
            if code == 200 and js:
                store.add_users([(uid, js.get("name"), js.get("name"),
                                  js.get("created"), time.time())])
                got += 1
            elif code == 429:
                time.sleep(float(hdr.get("Retry-After") or 30))
        except Exception:
            pass
        if progress and uid % 200 == 0:
            progress(got, uid)
        time.sleep(GATE)
    store.set_state("harvest_cursor", start + count)
    return got
