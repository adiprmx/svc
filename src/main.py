import logging, os, signal, threading, time

import backup, bot, config, doctor, store, worker

stop = threading.Event()


def setup_log():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler()])


def main():
    setup_log()
    log = logging.getLogger("svc")

    if config.DOCTOR:
        try:
            ok = doctor.preflight()
            if not ok and not config.FORCE:
                log.warning("doctor ada masalah -> SVC_FORCE=1 buat lanjut paksa")
        except Exception as e:
            log.warning("doctor error: %r", e)

    store.init(config.DB_PATH)
    store.set_shard(config.SHARD, config.SHARDS)

    if config.MODE == "worker":
        try:
            log.info("restore: %d hits", backup.restore())
        except Exception as e:
            log.warning("restore fail: %r", e)
        if not store.pending_count():
            try:
                import gencombo
                n, _, _ = gencombo.generate("spray")
                log.info("regen %d combo", n)
            except Exception as e:
                log.warning("regen fail: %r", e)

    store.reset_running()

    pool = worker.Pool(config.WORKERS, stop)
    if config.MODE == "worker":
        pool.paused = False
    pool.start()

    b = None
    if config.MODE != "worker" or os.environ.get("WORKER_BOT"):
        if config.BOT_TOKEN:
            owner = config.OWNER_ID
            if not owner:
                try:
                    with open(config.OWNER_FILE) as f:
                        owner = int(f.read().strip())
                except Exception:
                    owner = 0
            b = bot.Bot(config.BOT_TOKEN, owner, stop, pool)
            pool.notify = b.send
            threading.Thread(target=b.run, daemon=True).start()
            log.info("bot ON: %s... owner=%s auto=%s",
                     config.BOT_TOKEN[:12], owner or "(nunggu chat pertama)", config.AUTO_OWNER)
        else:
            log.warning("bot OFF: BOT_TOKEN kosong")

    def bg():
        while not stop.is_set():
            time.sleep(config.BACKUP_EVERY)
            try:
                backup.run()
            except Exception as e:
                log.warning("backup fail: %r", e)
    threading.Thread(target=bg, daemon=True).start()

    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())

    if b and b.chat:
        try:
            b.send("svc online | mode=%s workers=%d shard=%d/%d captcha=%s" % (
                config.MODE, config.WORKERS, config.SHARD, config.SHARDS, pool.mode))
            log.info("svc online terkirim")
        except Exception as e:
            log.warning("svc online gagal: %r", e)

    log.info("svc up mode=%s workers=%d shard=%d/%d captcha=%s",
             config.MODE, config.WORKERS, config.SHARD, config.SHARDS, pool.mode)

    t0 = time.time()
    while not stop.is_set():
        if config.DURATION and time.time() - t0 > config.DURATION:
            break
        time.sleep(1)
    stop.set()

    try:
        backup.run()
    except Exception:
        pass
    log.info("svc down")


if __name__ == "__main__":
    main()
