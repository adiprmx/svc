import os, subprocess, sys, time, traceback

import config, gencombo, rblx, store, util

OUT = []


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    OUT.append(line)


def step(name, fn):
    log("\n=== %s ===" % name)
    t0 = time.time()
    try:
        fn()
    except Exception:
        log("FAIL:\n" + traceback.format_exc())
    log("(%s) %.1fs" % (name, time.time() - t0))


def t_env():
    log("python", sys.version.split()[0], "| UA:", config.UA)
    log("BASE:", config.BASE)
    for m in ("config", "util", "store", "rblx", "worker", "bot", "farmer",
              "harvest", "gencombo", "backup", "probe", "pack"):
        __import__(m)
    log("semua modul ke-import")


def t_csrf():
    s = util.Session(config.UA, 15)
    code, hdr, text, js = s.request("GET", "https://auth.roblox.com/v2/login")
    log("GET /v2/login ->", code, "| x-csrf-token:", bool(hdr.get("x-csrf-token")))


def t_users():
    s = util.Session(config.UA, 15)
    code, hdr, text, js = s.request("GET", "https://users.roblox.com/v1/users/1")
    log("users/1 ->", code, "|", (js or {}).get("name"))


def t_ua():
    for ua in rblx.UAS:
        s = util.Session(ua, 15)
        s.request("GET", "https://auth.roblox.com/v2/login")
        code, hdr, text, js = s.request(
            "POST", "https://auth.roblox.com/v2/login",
            {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_pass_123"})
        st, det = rblx.classify(code, hdr, js, text)
        log("login %-46s -> %s %s" % (ua[:46], code, st))
        time.sleep(1.5)


def t_captcha_rate(n=8):
    tally = {}
    for i in range(n):
        s = util.Session(config.UA, 15)
        s.request("GET", "https://auth.roblox.com/v2/login")
        code, hdr, text, js = s.request(
            "POST", "https://auth.roblox.com/v2/login",
            {"ctype": "Username", "cvalue": "Roblox", "password": "dummy_%d" % i})
        st, det = rblx.classify(code, hdr, js, text)
        tally[st] = tally.get(st, 0) + 1
        log("  attempt %d -> %s" % (i + 1, st))
        time.sleep(1.2)
    log("CAPTCHA-RATE dari IP ini:", tally)


def t_store():
    db = os.path.join(config.DATA, "selftest.db")
    if os.path.exists(db):
        os.remove(db)
    store.init(db)
    store.add_users([(1, "roblox", "Roblox", "2006-02-27T00:00:00Z", time.time())])
    store.add_combos([("roblox", "x", time.time())])
    log("users:", store.stats()["users"], "| pending:", store.pending_count())
    job = store.claim_combo()
    log("claim:", job)
    st = store.requeue(job["username"], job["password"], "test", 0, 1)
    log("requeue ->", st, "| pending:", store.pending_count())
    log("hits:", store.hits())


def t_pack():
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pack.py")],
                       capture_output=True, text=True)
    log("pack rc=%s" % r.returncode, r.stdout.strip(), r.stderr.strip()[-400:])
    out = os.path.join(config.BASE, "svc.py")
    log("svc.py ada:", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0)


def main():
    step("env", t_env)
    step("csrf", t_csrf)
    step("users", t_users)
    step("ua-variants", t_ua)
    step("captcha-rate", t_captcha_rate)
    step("store", t_store)
    step("pack", t_pack)

    outdir = os.path.join(config.BASE, "out")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(OUT) + "\n")
    print("\n-> out/test.txt")


if __name__ == "__main__":
    main()
