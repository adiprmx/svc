import json, urllib.request

import config, store


def run():
    if not (config.GITHUB_TOKEN and config.GIST_ID):
        return False
    payload = json.dumps({
        "files": {"rbx-backup.json": {"content": store.export()}}
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/gists/" + config.GIST_ID,
        data=payload, method="PATCH",
        headers={"Authorization": "Bearer " + config.GITHUB_TOKEN,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "svc"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status == 200
