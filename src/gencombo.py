import os, time

import config, store


def load_passwords(path=None):
    path = path or config.PWFILE
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            p = line.rstrip("\r\n")
            if p:
                out.append(p)
    return out


def generate(mode="spray", pw_limit=None, user_limit=None, cap=None):
    users = store.all_usernames()
    if user_limit:
        users = users[:user_limit]
    pw = load_passwords()
    if pw_limit:
        pw = pw[:pw_limit]
    now = time.time()
    rows = []
    if mode == "spray":
        for p in pw:
            for u in users:
                rows.append((u, p, now))
    else:
        for u in users:
            for p in pw:
                rows.append((u, p, now))
    if cap:
        rows = rows[:cap]
    store.add_combos(rows)
    return len(rows), len(users), len(pw)
