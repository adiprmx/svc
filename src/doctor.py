import json, os, platform, sys, time
import urllib.error, urllib.parse, urllib.request

import config, rblx, util

OUT = []


def say(t=""):
    print(t, flush=True)
    OUT.append(str(t))


def tg(method, **p):
    url = "https://api.telegram.org/bot%s/%s" % (config.BOT_TOKEN, method)
    data = urllib.parse.urlencode(p).encode() if p else None
    try:
        with urllib.request.urlopen(url, data=data, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "err": "http %s" % e.code}
    except Exception as e:
        return {"ok": False, "err": repr(e)}


def out_ip():
    for u in ("https://api.ipify.org?format=json", "https://ifconfig.me/all.json"):
        try:
            with urllib.request.urlopen(u, timeout=10) as r:
                j = json.loads(r.read().decode())
            return j.get("ip") or j.get("ip_addr") or "?"
        except Exception:
            pass
    return "?"


def tg_check():
    ok = True
    if not config.BOT_TOKEN:
        say("[FAIL] BOT_TOKEN kosong")
        return False
    me = tg("getMe")
    if not me.get("ok"):
        ok = False
        say("[FAIL] getMe -> %s" % me)
        say("       token ini BUKAN punya bot lu, atau udah di-revoke.")
        say("       ambil ulang: @BotFather -> /mybots -> pilih bot -> API Token")
    else:
        u = (me.get("result") or {}).get("username")
        say("[ OK ] token valid, bot = @%s" % u)
    up = tg("getUpdates", limit=5)
    chats = []
    for x in (up.get("result") or []):
        c = ((x.get("message") or {}).get("chat") or {})
        if c.get("id"):
            chats.append((c.get("id"), c.get("username") or c.get("first_name")))
    if chats:
        say("[info] chat yang lagi antre: %s" % chats)
        if config.AUTO_OWNER and not config.OWNER_ID:
            say("[ OK ] AUTO_OWNER aktif -> chat %s bakal diadopsi jadi owner" % chats[0][0])
    else:
        say("[info] belum ada pesan antre (kirim /start ke bot dulu)")
    if config.OWNER_ID:
        if chats and all(c[0] != config.OWNER_ID for c in chats):
            say("[WARN] OWNER_ID=%s beda dari chat yang nge-chat (%s)" % (
                config.OWNER_ID, [c[0] for c in chats]))
        else:
            say("[ OK ] OWNER_ID=%s" % config.OWNER_ID)
    return ok


def net_check():
    say("[info] outbound IP: %s" % out_ip())
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    code, hdr, text, js = s.request("GET", "https://users.roblox.com/v1/users/1")
    say("[%s] users/1 -> %s" % (" OK " if code == 200 else "FAIL", code))
    return code == 200


def fp_check():
    profiles = [
        ("minimal", {"Origin": "https://www.roblox.com",
                     "Referer": "https://www.roblox.com/"}),
        ("browser+sec", dict(rblx.BROWSER_HDR, **rblx.SEC_HDR)),
    ]
    uas = ["Roblox/WinInet", rblx.UAS[2]]
    best = None
    for pname, extra in profiles:
        for ua in uas:
            s = util.Session(ua, 20)
            s.extra.update(extra)
            s.probe_csrf(rblx.AUTH + "/v2/logout")
            code, hdr, text, js = s.request(
                "POST", rblx.AUTH + "/v2/login",
                {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_1"})
            st, det = rblx.classify(code, hdr, js, text)
            tag = "%s/%s" % (pname, ua[:12])
            say("[%-14s] -> %s %s | cf=%s | ct=%s" % (
                tag, code, st, hdr.get("cf-mitigated") or "-",
                (hdr.get("content-type") or "-")[:24]))
            if st in ("invalid", "csrf", "captcha", "ratelimited", "2fa"):
                if best is None:
                    best = tag
            if st == "blocked" or code == 0:
                say("        body: %s" % (text or "")[:200].replace("\n", " "))
            time.sleep(0.8)
    if best:
        say("[ OK ] fingerprint yang nyampe API Roblox: %s" % best)
    else:
        say("[FAIL] semua profil ditolak -> kemungkinan WAF/IP. cek baris body di atas")
    return best is not None


def preflight():
    say("=" * 46)
    say(" svc doctor")
    say("=" * 46)
    say(config.describe())
    say("-" * 46)
    a = tg_check()
    say("-" * 46)
    b = net_check()
    say("-" * 46)
    c = fp_check()
    say("-" * 46)
    for p in config.problems():
        say("[WARN] %s" % p)
    ok = a and b
    say("HASIL: %s" % ("SIAP" if ok else "ADA MASALAH"))
    say("=" * 46)
    try:
        os.makedirs(os.path.join(config.BASE, "out"), exist_ok=True)
        with open(os.path.join(config.BASE, "out", "doctor.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    except Exception:
        pass
    return ok
