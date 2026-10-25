import json, os, sys, time
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
    t = config.BOT_TOKEN
    say("[info] token len=%d ascii=%s bot_id=%s" % (len(t), t.isascii(), t.split(":")[0]))
    if not t:
        say("[FAIL] BOT_TOKEN kosong")
        return False
    me = tg("getMe")
    if not me.get("ok"):
        say("[FAIL] getMe -> %s" % me)
        if me.get("error_code") == 404:
            say("       token-nya gak match / ada karakter invisible.")
            say("       coba: re-copy token dari BotFather, tempel ulang di .env")
        elif me.get("error_code") == 401:
            say("       token salah atau udah di-revoke -> ambil ulang di @BotFather")
        return False
    say("[ OK ] token valid, bot = @%s" % (me.get("result") or {}).get("username"))
    up = tg("getUpdates", limit=5)
    chats = [((x.get("message") or {}).get("chat") or {}).get("id")
             for x in (up.get("result") or [])]
    chats = [c for c in chats if c]
    if chats:
        say("[info] chat antre: %s" % chats)
        if config.AUTO_OWNER and not config.OWNER_ID:
            say("[ OK ] AUTO_OWNER aktif -> chat %s bakal diadopsi" % chats[0])
    else:
        say("[info] belum ada pesan antre (kirim /start ke bot dulu)")
    if config.OWNER_ID:
        say("[ OK ] OWNER_ID=%s" % config.OWNER_ID)
    return True


def net_check():
    say("[info] outbound IP: %s" % out_ip())
    s = util.Session(config.UA, 15)
    s.extra.update(rblx.BROWSER_HDR)
    code, hdr, text, js = s.request("GET", "https://users.roblox.com/v1/users/1")
    say("[%s] users/1 -> %s" % (" OK " if code == 200 else "FAIL", code))
    return code == 200


def csrf_check():
    say("== csrf probe ==")
    best = None
    for method, url, body in rblx.CSRF_PROBES:
        s = util.Session("Roblox/WinInet", 15)
        s.extra.update(rblx.BROWSER_HDR)
        code, hdr, text, js = s.request(method, url, body)
        got = bool(hdr.get("x-csrf-token"))
        say("  %-6s %-42s -> %s csrf=%s" % (method, url.replace("https://", "")[:42],
                                            code, "ADA" if got else "kosong"))
        if got and best is None:
            best = url
        time.sleep(0.3)
    say("[%s] csrf probe: %s" % (" OK " if best else "FAIL", best or "gak ada yang kasih token"))
    return bool(best)


def fp_check():
    profiles = [("minimal", dict(rblx.BROWSER_HDR)),
                ("browser+sec", dict(rblx.BROWSER_HDR, **rblx.SEC_HDR))]
    uas = ["Roblox/WinInet", rblx.UAS[2]]
    best = None
    for pname, extra in profiles:
        for ua in uas:
            cli = rblx.Roblox(ua)
            cli.s.extra.update(extra)
            tok = cli.csrf()
            code, hdr, text, js = cli.s.request(
                "POST", rblx.AUTH + "/v2/login",
                {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_1"})
            st, det = classify_safe(code, hdr, js, text)
            say("[%-18s] -> %s %s | csrf=%s" % (pname + "/" + ua[:10], code, st,
                                                "ada" if tok else "KOSONG"))
            if st in ("invalid", "csrf", "captcha", "ratelimited", "2fa"):
                best = best or ("%s/%s" % (pname, ua[:10]))
            if st in ("blocked", "denied", "csrf"):
                say("        body: %s" % (text or "")[:180].replace("\n", " "))
            time.sleep(0.8)
    say("[%s] fingerprint: %s" % (" OK " if best else "FAIL", best or "gak ada yang nembus"))
    return bool(best)


def classify_safe(code, hdr, js, text):
    try:
        return rblx.classify(code, hdr, js, text)
    except Exception as e:
        return "error", repr(e)


def preflight():
    say("=" * 46)
    say(" svc doctor v2")
    say("=" * 46)
    say(config.describe())
    say("-" * 46)
    a = tg_check()
    say("-" * 46)
    b = net_check()
    say("-" * 46)
    c = csrf_check()
    say("-" * 46)
    d = fp_check()
    say("-" * 46)
    for p in config.problems():
        say("[WARN] %s" % p)
    ok = a and b and c and d
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
