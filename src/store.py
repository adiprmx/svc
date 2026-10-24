import json, sqlite3, threading, time

_lock = threading.RLock()
_db = None
_shard = (0, 1)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT UNIQUE, name TEXT, created TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS combos(
    username TEXT, password TEXT, status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, ctries INTEGER DEFAULT 0,
    detail TEXT, ts REAL, PRIMARY KEY(username, password));
CREATE TABLE IF NOT EXISTS hits(
    username TEXT PRIMARY KEY, password TEXT, cookie TEXT, data TEXT, note TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_combos_status ON combos(status, next_try);
"""


def _k(u):
    return (u or "").strip().lower()


def _cols(table):
    return {r["name"] for r in _db.execute("PRAGMA table_info(%s)" % table)}


def init(path):
    global _db
    _db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    _db.row_factory = sqlite3.Row
    with _lock:
        _db.executescript(SCHEMA)
        for tbl, col, ddl in (("users", "name", "TEXT"),
                              ("combos", "attempts", "INTEGER DEFAULT 0"),
                              ("combos", "next_try", "REAL DEFAULT 0"),
                              ("combos", "ctries", "INTEGER DEFAULT 0"),
                              ("hits", "note", "TEXT")):
            if col not in _cols(tbl):
                _db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, ddl))
        _db.execute("UPDATE combos SET next_try=0 WHERE next_try IS NULL")
        _db.execute("UPDATE combos SET attempts=0 WHERE attempts IS NULL")
        _db.execute("UPDATE combos SET ctries=0 WHERE ctries IS NULL")
        _db.commit()


def set_shard(idx, total):
    global _shard
    _shard = (max(0, int(idx)), max(1, int(total)))


def close():
    global _db
    with _lock:
        if _db is not None:
            _db.close()
            _db = None


def add_users(rows):
    with _lock:
        _db.executemany(
            "INSERT OR IGNORE INTO users(id, username, name, created, ts) VALUES(?,?,?,?,?)",
            [(r[0], _k(r[1]), r[2], r[3], r[4]) for r in rows])
        _db.commit()


def all_usernames():
    with _lock:
        return [r["username"] for r in
                _db.execute("SELECT username FROM users ORDER BY id")]


def add_combos(rows, chunk=5000):
    with _lock:
        for i in range(0, len(rows), chunk):
            _db.executemany(
                "INSERT OR IGNORE INTO combos(username, password, ts) VALUES(?,?,?)",
                [(_k(u), p, t) for u, p, t in rows[i:i + chunk]])
        _db.commit()


def claim_combo():
    now = time.time()
    idx, tot = _shard
    with _lock:
        if tot > 1:
            r = _db.execute(
                "SELECT username, password, attempts FROM combos "
                "WHERE status='pending' AND next_try<=? AND (rowid % ?)=? "
                "ORDER BY next_try, rowid LIMIT 1", (now, tot, idx)).fetchone()
        else:
            r = _db.execute(
                "SELECT username, password, attempts FROM combos "
                "WHERE status='pending' AND next_try<=? "
                "ORDER BY next_try, rowid LIMIT 1", (now,)).fetchone()
        if not r:
            return None
        _db.execute("UPDATE combos SET status='running', attempts=attempts+1, ts=? "
                    "WHERE username=? AND password=?",
                    (now, r["username"], r["password"]))
        _db.commit()
        return {"username": r["username"], "password": r["password"],
                "attempts": r["attempts"] + 1}


def finish_combo(u, p, status, detail="", delay=0.0):
    now = time.time()
    with _lock:
        _db.execute("UPDATE combos SET status=?, detail=?, ts=?, next_try=? "
                    "WHERE username=? AND password=?",
                    (status, (detail or "")[:300], now, now + delay, _k(u), p))
        _db.commit()


def requeue(u, p, detail="", delay=0.0, max_attempts=3):
    now = time.time()
    with _lock:
        r = _db.execute("SELECT attempts FROM combos WHERE username=? AND password=?",
                        (_k(u), p)).fetchone()
        att = r["attempts"] if r else max_attempts
        status = "pending" if att < max_attempts else "dead"
        _db.execute("UPDATE combos SET status=?, detail=?, ts=?, next_try=? "
                    "WHERE username=? AND password=?",
                    (status, (detail or "")[:300], now, now + delay, _k(u), p))
        _db.commit()
        return status


def mark_captcha(u, p, detail="", delay=0.0, max_tries=5):
    """Captcha BUKAN bukti salah password. ctries kepisah dari attempts."""
    now = time.time()
    with _lock:
        _db.execute("UPDATE combos SET status='captcha', ctries=ctries+1, "
                    "detail=?, ts=?, next_try=? WHERE username=? AND password=?",
                    ((detail or "")[:300], now, now + delay, _k(u), p))
        _db.commit()


def captcha_count():
    with _lock:
        return _db.execute("SELECT COUNT(*) c FROM combos "
                           "WHERE status='captcha'").fetchone()["c"]


def captcha_list(limit=15):
    with _lock:
        return ["%s : %s  [%s/%d]" % (r["username"], r["password"],
                                      (r["detail"] or "")[:40], r["ctries"])
                for r in _db.execute(
                    "SELECT username, password, detail, ctries FROM combos "
                    "WHERE status='captcha' ORDER BY ts LIMIT ?", (limit,))]


def retry_captcha(max_tries=5):
    """Balikin combo captcha ke pending. Yang udah kelewat batas -> dead."""
    with _lock:
        n = _db.execute("SELECT COUNT(*) c FROM combos WHERE status='captcha' "
                        "AND ctries < ?", (max_tries,)).fetchone()["c"]
        _db.execute("UPDATE combos SET status='pending', next_try=0 "
                    "WHERE status='captcha' AND ctries < ?", (max_tries,))
        _db.execute("UPDATE combos SET status='dead' "
                    "WHERE status='captcha' AND ctries >= ?", (max_tries,))
        _db.commit()
    return n


def reset_running():
    with _lock:
        _db.execute("UPDATE combos SET status='pending', next_try=0 WHERE status='running'")
        _db.commit()


def retry_dead():
    with _lock:
        n = _db.execute("SELECT COUNT(*) c FROM combos WHERE status='dead'").fetchone()["c"]
        _db.execute("UPDATE combos SET status='pending', attempts=0, ctries=0, next_try=0 "
                    "WHERE status='dead'")
        _db.commit()
    return n


def add_hit(u, p, cookie, note=""):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO hits(username, password, cookie, data, note, ts) "
                    "VALUES(?,?,?,?,?,?)", (_k(u), p, cookie, "", note, time.time()))
        _db.commit()


def set_hit_data(u, data):
    with _lock:
        _db.execute("UPDATE hits SET data=? WHERE username=?", (data, _k(u)))
        _db.commit()


def hits(limit=30):
    with _lock:
        return [dict(r) for r in _db.execute(
            "SELECT username, password, cookie, data, note, ts FROM hits "
            "ORDER BY ts DESC LIMIT ?", (limit,))]


def get_hit(u):
    with _lock:
        r = _db.execute("SELECT * FROM hits WHERE username=?", (_k(u),)).fetchone()
        return dict(r) if r else None


def dead_list(limit=15):
    with _lock:
        return ["%s : %s  [%s]" % (r["username"], r["password"], (r["detail"] or "")[:40])
                for r in _db.execute(
                    "SELECT username, password, detail FROM combos "
                    "WHERE status='dead' LIMIT ?", (limit,))]


def pending_count():
    with _lock:
        return _db.execute("SELECT COUNT(*) c FROM combos "
                           "WHERE status='pending'").fetchone()["c"]


def get_state(k, default=None):
    with _lock:
        r = _db.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default


def set_state(k, v):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO state(k, v) VALUES(?,?)", (k, str(v)))
        _db.commit()


def stats():
    with _lock:
        rows = _db.execute("SELECT status, COUNT(*) c FROM combos GROUP BY status").fetchall()
        u = _db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        h = _db.execute("SELECT COUNT(*) c FROM hits").fetchone()["c"]
    return {"combos": {r["status"]: r["c"] for r in rows}, "users": u, "hits": h}


def export(full=True):
    with _lock:
        out = {"hits": [dict(r) for r in _db.execute("SELECT * FROM hits")],
               "state": [dict(r) for r in _db.execute("SELECT * FROM state")]}
        if full:
            out["users"] = [dict(r) for r in _db.execute("SELECT * FROM users")]
            out["combos"] = [dict(r) for r in _db.execute(
                "SELECT username, password, status, attempts, next_try, ctries, ts FROM combos")]
    return json.dumps(out, default=str)


def restore(payload):
    data = json.loads(payload or "{}")
    now = time.time()
    with _lock:
        for h in data.get("hits", []):
            _db.execute("INSERT OR REPLACE INTO hits(username, password, cookie, data, note, ts) "
                        "VALUES(?,?,?,?,?,?)",
                        (_k(h.get("username")), h.get("password"), h.get("cookie"),
                         h.get("data"), h.get("note"), h.get("ts") or now))
        for s in data.get("state", []):
            _db.execute("INSERT OR REPLACE INTO state(k, v) VALUES(?,?)",
                        (s.get("k"), s.get("v")))
        for u in data.get("users", []):
            _db.execute("INSERT OR IGNORE INTO users(id, username, name, created, ts) "
                        "VALUES(?,?,?,?,?)",
                        (u.get("id"), _k(u.get("username")), u.get("name"),
                         u.get("created"), u.get("ts") or now))
        for c in data.get("combos", []):
            _db.execute(
                "INSERT OR IGNORE INTO combos"
                "(username, password, status, attempts, next_try, ctries, ts) VALUES(?,?,?,?,?,?,?)",
                (_k(c.get("username")), c.get("password"), c.get("status") or "pending",
                 c.get("attempts") or 0, c.get("next_try") or 0, c.get("ctries") or 0,
                 c.get("ts") or now))
        _db.commit()
    return len(data.get("hits", []))
