import json, urllib.request

import config, store

FILE = "rbx-backup.json"


def _hdr():
    return {"Authorization": "Bearer " + config.GITHUB_TOKEN,
            "Accept": "application/vnd.github+json",
            "User-Agent": "svc"}


def run():
    if not (config.GITHUB_TOKEN and config.GIST_ID):
        return False
    payload = json.dumps({
        "files": {FILE: {"content": store.export(config.BACKUP_FULL)}}
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/gists/" + config.GIST_ID,
        data=payload, method="PATCH",
        headers=dict(_hdr(), **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status == 200


def restore():
    if not (config.GITHUB_TOKEN and config.GIST_ID):
        return 0
    req = urllib.request.Request(
        "https://api.github.com/gists/" + config.GIST_ID, headers=_hdr())
    with urllib.request.urlopen(req, timeout=120) as r:
        js = json.loads(r.read().decode())
    f = (js.get("files") or {}).get(FILE)
    if not f:
        return 0
    content = f.get("content")
    if not content and f.get("raw_url"):
        with urllib.request.urlopen(f["raw_url"], timeout=120) as r:
            content = r.read().decode()
    return store.restore(content or "{}")
