import time

import config, rblx, util


def cap_probe():
    out = ["== captcha raw probe =="]
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    s.probe_csrf(rblx.AUTH + "/v2/logout")
    code, hdr, text, js = s.request(
        "POST", rblx.AUTH + "/v2/login",
        {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_%d" % int(time.time())})
    out.append("status : %s" % code)
    for k in ("rblx-challenge-id", "rblx-challenge-type", "rblx-challenge-metadata",
              "cf-mitigated", "content-type", "server"):
        v = hdr.get(k)
        out.append("%s: %s" % (k, str(v)[:300] if v else "-"))
    ch = rblx.parse_challenge(hdr)
    out.append("parsed id : %s" % ch.get("id"))
    out.append("parsed typ: %s" % ch.get("type"))
    out.append("meta keys : %s" % sorted((ch.get("meta") or {}).keys()))
    out.append("blob len  : %d" % len(ch.get("blob") or ""))
    out.append("publickey : %s" % (ch.get("public_key") or "-"))
    out.append("body      : %s" % (text or "")[:300].replace("\n", " "))
    return "\n".join(out)


def main():
    out = ["== probe endpoint =="]
    for ua in rblx.UAS:
        s = util.Session(ua, 15)
        s.extra.update(rblx.BROWSER_HDR)
        code, hdr, text, js = s.request("GET", rblx.AUTH + "/v2/login")
        out.append("csrf %-45s -> %s token=%s" % (ua[:45], code,
                                                  bool(hdr.get("x-csrf-token"))))
    out.append("")
    out.append(cap_probe())
    return "\n".join(out)
