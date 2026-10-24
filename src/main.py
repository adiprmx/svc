import logging, os, signal, threading, time

import backup, bot, config, store, worker

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

    mode = (os.environ.get("SVCMODE") or "full").lower()
    duration = int(os.environ.get("SVC_DURATION") or 0)

    store.init(config.DB_PATH)
    store.set_shard(config.SHARD, config.SHARDS)

    if mode == "worker":
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
    if mode == "worker":
        pool.paused = False
    pool.start()

    b = None
    if mode != "worker" or os.environ.get("WORKER_BOT"):
        if config.BOT_TOKEN and config.OWNER_ID:
            b = bot.Bot(config.BOT_TOKEN, config.OWNER_ID, stop, pool)
            pool.notify = b.send
            threading.Thread(target=b.run, daemon=True).start()

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

    if b:
        try:
            b.send("svc online | mode=%s workers=%d shard=%d/%d captcha=%s" % (
                mode, config.WORKERS, config.SHARD, config.SHARDS, pool.mode))
        except Exception:
            pass

    log.info("svc up mode=%s workers=%d shard=%d/%d captcha=%s",
             mode, config.WORKERS, config.SHARD, config.SHARDS, pool.mode)
    if duration:
        t0 = time.time()
        while not stop.is_set() and time.time() - t0 < duration:
            time.sleep(1)
        stop.set()
    else:
        while not stop.is_set():
            time.sleep(1)

    try:
        backup.run()
    except Exception:
        pass
    log.info("svc down")


if __name__ == "__main__":
    main()
