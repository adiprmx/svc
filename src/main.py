import signal, threading, time

import backup, bot, config, store, worker

stop = threading.Event()


def main():
    store.init(config.DB_PATH)
    store.reset_running()

    pool = worker.Pool(config.WORKERS, stop)
    pool.start()

    b = bot.Bot(config.BOT_TOKEN, config.OWNER_ID, stop, pool)
    threading.Thread(target=b.run, daemon=True).start()

    def bg():
        while not stop.is_set():
            time.sleep(600)
            try:
                backup.run()
            except Exception:
                pass
    threading.Thread(target=bg, daemon=True).start()

    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())

    if config.BOT_TOKEN and config.OWNER_ID:
        try:
            b.send("svc online")
        except Exception:
            pass

    while not stop.is_set():
        time.sleep(1)


if __name__ == "__main__":
    main()
