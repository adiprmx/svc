import json, sqlite3, threading, time

_lock = threading.RLock()
_db = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT, name TEXT, created TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS combos(
    username TEXT, password TEXT, status TEXT DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0,
    detail TEXT, ts REAL, PRIMARY KEY(username, password));
CREATE TABLE IF NOT EXISTS hits(
    username TEXT PRIMARY KEY, password TEXT, cookie TEXT, data TEXT, ts REAL);
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
                              ("combos", "next_try", "REAL DEFAULT 0")):
            if col not in _cols(tbl):
                _db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, ddl))
        _db.execute("UPDATE combos SET next_try=0 WHERE next_try IS NULL")
        _db.execute("UPDATE combos SET attempts=0 WHERE attempts IS NULL")
        _db.commit()


def add_users(rows):
    with _lock:
        _db.executemany(
            "INSERT OR IGNORE INTO users(id, username, name, created, ts) VALUES(?,?,?,?,?)",
            [(_k(u), ) and r for r in rows])
        _db.commit()
