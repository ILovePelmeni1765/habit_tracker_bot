# main.py

import config
import storage
from scheduler import ReminderScheduler
from bot import bot


def main():
    if not config.BOT_TOKEN or "ВСТАВЬ_СВОЙ_ТОКЕН" in config.BOT_TOKEN:
        raise RuntimeError("Сначала вставь токен бота в config.BOT_TOKEN")

    # Инициализируем БД
    storage.init_db()

    # Запускаем планировщик напоминаний
    scheduler = ReminderScheduler(config.BOT_TOKEN)
    scheduler.start()

    # Запускаем бота (long-polling через maxgram)
    try:
        bot.run()
    except KeyboardInterrupt:
        scheduler.stop()
        print("Остановка бота...")


if __name__ == "__main__":
    main()
