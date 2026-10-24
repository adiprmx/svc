import time

import util

UA_A = "Roblox/WinInet"
UA_B = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PROBES = [
    ("GET",  "https://auth.roblox.com/v2/login", None),
    ("POST", "https://auth.roblox.com/v2/login", None),
    ("POST", "https://auth.roblox.com/v2/logout", None),
    ("GET",  "https://www.roblox.com/home", None),
]

KEYS = ["x-csrf-token", "rblx-challenge-id", "rblx-challenge-type",
        "content-type", "server", "cf-mitigated", "set-cookie"]


def main():
    for ua in (UA_A, UA_B):
        for extra in ({}, {"Origin": "https://www.roblox.com",
                           "Referer": "https://www.roblox.com/"}):
            for method, url, body in PROBES:
                s = util.Session(ua, 15)
                s.extra.update(extra)
                try:
                    code, hdr, text, js = s.request(method, url, body)
                except Exception as e:
                    print("ERR", e)
                    continue
                print("\n--- %s %s | ua=%s | origin=%s" % (
                    method, url.replace("https://", ""), ua[:16], bool(extra)))
                print("    status:", code)
                for k in KEYS:
                    v = hdr.get(k)
                    if v:
                        print("    %s: %s" % (k, str(v)[:140]))
                print("    body:", (text or "")[:400].replace("\n", " "))
                time.sleep(0.6)


if __name__ == "__main__":
    main()
