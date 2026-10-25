import json, logging, urllib.request

import config, store

log = logging.getLogger("svc.backup")
FILE = "rbx-backup-%d.json"


def _hdr():
    return {"Authorization": "Bearer " + config.GITHUB_TOKEN,
            "Accept": "application/vnd.github+json", "User-Agent": "svc"}


def _url():
    return "https://api.github.com/gists/" + config.GIST_ID


def enabled():
    return bool(config.GITHUB_TOKEN and config.GIST_ID)


def run():
    if not enabled():
        return False
    payload = json.dumps({"files": {FILE % config.SHARD: {
        "content": store.export(config.BACKUP_FULL)}}}).encode()
    req = urllib.request.Request(_url(), data=payload, method="PATCH",
                                headers=dict(_hdr(), **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status == 200


def restore():
    if not enabled():
        return 0
    req = urllib.request.Request(_url(), headers=_hdr())
    with urllib.request.urlopen(req, timeout=120) as r:
        js = json.loads(r.read().decode())
    total = 0
    for name, f in (js.get("files") or {}).items():
        if not name.startswith("rbx-backup"):
            continue
        content = None if f.get("truncated") else f.get("content")
        if not content and f.get("raw_url"):
            try:
                with urllib.request.urlopen(f["raw_url"], timeout=180) as r2:
                    content = r2.read().decode()
            except Exception:
                content = None
        if content:
            try:
                total += store.restore(content)
            except Exception as e:
                log.warning("restore %s gagal: %r", name, e)
    return total
