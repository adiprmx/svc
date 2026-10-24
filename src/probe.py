import time

import config, util

UAS = [
    "Roblox/WinInet",
    "Roblox/2.616.551 (Android; Android 12; SM-G991B)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]


def main():
    out = ["== probe endpoint =="]
    for ua in UAS:
        s = util.Session(ua, 15)
        code, hdr, text, js = s.request("GET", "https://auth.roblox.com/v2/login")
        out.append("csrf %-45s -> %s token=%s" % (ua[:45], code, bool(hdr.get("x-csrf-token"))))

    out.append("")
    out.append("== probe login akun dummy ==")
    for ua in UAS:
        s = util.Session(ua, 15)
        s.request("GET", "https://auth.roblox.com/v2/login")
        code, hdr, text, js = s.request("POST", "https://auth.roblox.com/v2/login",
                                        {"ctype": "Username", "cvalue": "Roblox",
                                         "password": "dummy_pass_123"})
        out.append("%-45s -> %s challenge=%s msg=%s" % (
            ua[:45], code, bool(hdr.get("rblx-challenge-id")),
            (js or {}).get("errors", [{}])[0].get("message", "")[:60]))
        time.sleep(1.5)

    out.append("")
    out.append("== batas rate (20 GET) ==")
    s = util.Session(config.UA, 15)
    t0, ok, rl = time.time(), 0, 0
    for i in range(20):
        code, hdr, text, js = s.request("GET", "https://auth.roblox.com/v2/login")
        if code == 403:
            ok += 1
        if code == 429:
            rl += 1
    out.append("20 request / %.1fs | ok=%d | 429=%d" % (time.time() - t0, ok, rl))
    return "\n".join(out)
