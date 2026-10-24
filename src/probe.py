import time

import config, rblx, util

UAS = [
    "Roblox/WinInet",
    "Roblox/2.616.551 (Android; Android 12; SM-G991B)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]


def cap_probe():
    """Dump header challenge mentah. Jalanin ini dulu sebelum percaya warm flow."""
    out = ["== captcha raw probe =="]
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    s.request("GET", rblx.AUTH + "/v2/login")
    code, hdr, text, js = s.request(
        "POST", rblx.AUTH + "/v2/login",
        {"ctype": "Username", "cvalue": "Roblox",
         "password": "dummy_%d" % int(time.time())})
    out.append("status: %s" % code)
    for k in ("rblx-challenge-id", "rblx-challenge-type", "rblx-challenge-metadata"):
        v = hdr.get(k)
        out.append("%s: %s" % (k, str(v)[:500] if v else "-"))
    ch = rblx.parse_challenge(hdr)
    out.append("parsed id  : %s" % ch.get("id"))
    out.append("parsed type: %s" % ch.get("type"))
    out.append("inner keys : %s" % sorted((ch.get("inner") or {}).keys()))
    out.append("blob len   : %d" % len(((ch.get("inner") or {}).get("blob") or "")))
    out.append("body: %s" % (text or "")[:200].replace("\n", " "))
    return "\n".join(out)


def main():
    out = ["== probe endpoint =="]
    for ua in UAS:
        s = util.Session(ua, 15)
        code, hdr, text, js = s.request("GET", "https://auth.roblox.com/v2/login")
        out.append("csrf %-45s -> %s token=%s" % (ua[:45], code, bool(hdr.get("x-csrf-token"))))

    out.append("")
    out.append(cap_probe())

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
