import json, sqlite3, threading, time

_lock = threading.RLock()
_db = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT UNIQUE, created TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS combos(
    username TEXT, password TEXT, status TEXT DEFAULT 'pending',
    detail TEXT, ts REAL, PRIMARY KEY(username, password));
CREATE TABLE IF NOT EXISTS hits(
    username TEXT PRIMARY KEY, password TEXT, cookie TEXT, data TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_combos_status ON combos(status);
"""


def init(path):
    global _db
    _db = sqlite3.connect(path, check_same_thread=False, timeout=30)
    _db.row_factory = sqlite3.Row
    with _lock:
        _db.executescript(SCHEMA)
        _db.commit()


def add_users(rows):
    with _lock:
        _db.executemany(
            "INSERT OR IGNORE INTO users(id, username, created, ts) VALUES(?,?,?,?)", rows)
        _db.commit()


def all_usernames():
    with _lock:
        return [r["username"] for r in
                _db.execute("SELECT username FROM users ORDER BY id")]


def add_combos(rows, chunk=10000):
    with _lock:
        for i in range(0, len(rows), chunk):
            _db.executemany(
                "INSERT OR IGNORE INTO combos(username, password, ts) VALUES(?,?,?)",
                rows[i:i + chunk])
        _db.commit()


def claim_combo():
    with _lock:
        r = _db.execute("SELECT username, password FROM combos "
                        "WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
        if not r:
            return None
        _db.execute("UPDATE combos SET status='running', ts=? "
                    "WHERE username=? AND password=?",
                    (time.time(), r["username"], r["password"]))
        _db.commit()
        return dict(r)


def finish_combo(u, p, status, detail=""):
    with _lock:
        _db.execute("UPDATE combos SET status=?, detail=?, ts=? "
                    "WHERE username=? AND password=?",
                    (status, (detail or "")[:300], time.time(), u, p))
        _db.commit()


def reset_running():
    with _lock:
        _db.execute("UPDATE combos SET status='pending' WHERE status='running'")
        _db.commit()


def add_hit(u, p, cookie, note=""):
    with _lock:
        _db.execute("INSERT OR REPLACE INTO hits(username, password, cookie, data, ts) "
                    "VALUES(?,?,?,?,?)", (u, p, cookie, note, time.time()))
        _db.commit()


def set_hit_data(u, data):
    with _lock:
        _db.execute("UPDATE hits SET data=? WHERE username=?", (data, u))
        _db.commit()


def hits(limit=30):
    with _lock:
        return [dict(r) for r in _db.execute(
            "SELECT username, password, data, ts FROM hits ORDER BY ts DESC LIMIT ?",
            (limit,))]


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


def export():
    with _lock:
        out = {}
        for t in ("users", "combos", "hits"):
            out[t] = [dict(r) for r in _db.execute("SELECT * FROM %s" % t)]
    return json.dumps(out)
