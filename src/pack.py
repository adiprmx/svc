import base64, io, os, random, zipfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) in (".s", "src") else HERE
OUT = os.path.join(ROOT, "svc.py")
ENTRY = "main.py"
ENTRY_NAME = "app.py"
SKIP = {"pack.py", "svc.py"}

STUB = '''#!/usr/bin/env python3
import base64, compileall, hashlib, io, os, runpy, sys, zipfile, zlib

_K = {key!r}
_M = b"#__P__"


def _load():
    src = open(os.path.abspath(__file__), "rb").read()
    blob = b"".join(src[src.index(_M) + len(_M):].split())
    raw = base64.b64decode(blob)
    k = _K
    return zlib.decompress(bytes(b ^ k[n % len(k)] for n, b in enumerate(raw)))


def main():
    os.environ["SVCHOME"] = os.path.dirname(os.path.abspath(__file__))
    blob = _load()
    h = hashlib.sha256(blob).hexdigest()[:16]
    d = os.path.join(os.path.expanduser("~"), ".cache", "svc-" + h)
    if not os.path.exists(os.path.join(d, ".ok")):
        os.makedirs(d, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(blob)).extractall(d)
        try:
            compileall.compile_dir(d, quiet=2, legacy=True)
            for f in os.listdir(d):
                if f.endswith(".py"):
                    os.remove(os.path.join(d, f))
        except Exception:
            pass
        open(os.path.join(d, ".ok"), "w").write("1")
    sys.path.insert(0, d)
    runpy.run_module("app", run_name="__main__")


main()
'''


def read_env():
    p = os.path.join(ROOT, ".env")
    env = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    files = sorted(f for f in os.listdir(HERE)
                   if f.endswith(".py") and f not in SKIP)
    if ENTRY not in files:
        raise SystemExit("main.py gak ketemu di " + HERE)

    secret = read_env()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(HERE, f), ENTRY_NAME if f == ENTRY else f)
        if secret:
            z.writestr("_secret.py", "_SECRET = " + repr(secret) + "\n")

    key = bytes(random.randrange(256) for _ in range(32))
    comp = zlib.compress(buf.getvalue(), 9)
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(comp))
    b64 = base64.b64encode(xored).decode()
    body = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(STUB.format(key=key))
        fh.write("\n#__P__\n")
        fh.write(body + "\n")
    os.chmod(OUT, 0o755)
    print("ok -> %s (%d KB)" % (OUT, os.path.getsize(OUT) // 1024))


main()
