import time

import config, store, util

GATE = 0.25
BATCH = 100
BULK = "https://users.roblox.com/v1/users"


def _one(s, uid):
    code, hdr, text, js = s.request(BULK.rsplit("/", 1)[0] + "/v1/users/%d" % uid)
    if code == 200 and js:
        store.add_users([(uid, js.get("name"), js.get("displayName"),
                          js.get("created"), time.time())])
        return 1
    return 0


def run(start, count, stop, progress=None):
    s = util.Session(config.UA, config.HTTP_TIMEOUT, config.PROXY or None)
    got = 0
    uid = start
    end = start + count
    while uid < end and not stop.is_set():
        ids = list(range(uid, min(uid + BATCH, end)))
        try:
            code, hdr, text, js = s.request("POST", BULK, {"userIds": ids})
        except Exception:
            code, hdr, js = 0, {}, None
        if code == 200 and isinstance(js, dict):
            rows = [(u.get("id"), u.get("name"), u.get("displayName"),
                     u.get("created"), time.time()) for u in js.get("data") or []]
            if rows:
                store.add_users(rows)
                got += len(rows)
            uid += BATCH
        elif code == 429:
            time.sleep(float(hdr.get("Retry-After") or 5))
            continue
        elif code == 400:
            # batch ditolak (ada id aneh) -> fallback satu-satu
            for i in ids:
                if stop.is_set():
                    break
                got += _one(s, i)
                time.sleep(GATE)
            uid += BATCH
        else:
            time.sleep(1.5)
            uid += BATCH
        store.set_state("harvest_cursor", uid)
        if progress and (uid // BATCH) % 20 == 0:
            progress(got, uid)
        time.sleep(GATE)
    return got
