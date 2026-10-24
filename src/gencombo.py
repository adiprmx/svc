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


def save_passwords(pw):
    seen, out = set(), []
    for p in pw:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    os.makedirs(os.path.dirname(config.PWFILE), exist_ok=True)
    with open(config.PWFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + ("\n" if out else ""))
    return len(out)


def generate(mode="spray", pw_limit=None, user_limit=None, cap=None, chunk=100000):
    users = store.all_usernames()
    if user_limit:
        users = users[:user_limit]
    pw = load_passwords()
    if pw_limit:
        pw = pw[:pw_limit]
    now = time.time()
    total = 0
    batch = []

    def flush():
        nonlocal batch, total
        if batch:
            store.add_combos(batch)
            total += len(batch)
            batch = []

    if mode == "spray":
        for p in pw:
            for u in users:
                batch.append((u, p, now))
                if len(batch) >= chunk:
                    flush()
                if cap and total >= cap:
                    flush()
                    return total, len(users), len(pw)
    else:
        for u in users:
            for p in pw:
                batch.append((u, p, now))
                if len(batch) >= chunk:
                    flush()
                if cap and total >= cap:
                    flush()
                    return total, len(users), len(pw)
    flush()
    return total, len(users), len(pw)
