# scheduler.py
"""
Планировщик напоминаний.

Отдельный поток, который регулярно опрашивает БД с напоминаниями
и отправляет сообщения пользователям через HTTP API MAX.

Особенности:
- учитывает часовой пояс пользователя (storage.get_user_timezone_offset);
- поддерживает два вида напоминаний:
    * kind="fixed"    — в конкретное локальное время HH:MM;
    * kind="interval" — каждые N минут в указанный день недели;
- напоминания проверяются раз в минуту и стараются приходить ровно в `..:..:00`.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import requests

import config
import storage

logger = logging.getLogger("reminder_scheduler")

API_URL = "https://platform-api.max.ru/messages"


def _get_user_now(offset_minutes: int) -> datetime:
    """
    Текущее локальное время пользователя с учётом смещения в минутах от UTC.
    """
    tz = timezone(timedelta(minutes=offset_minutes))
    return datetime.now(tz)


def _send_message(token: str, user_id: int, text: str) -> None:
    """
    Отправка сообщения напрямую через HTTP API MAX.

    Важно:
    - получатель (user_id) должен быть в query-параметрах;
    - текст сообщения — в JSON-теле.
    """
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    params = {
        "user_id": user_id,
    }
    payload = {
        "text": text,
    }

    try:
        resp = requests.post(
            API_URL,
            params=params,
            json=payload,
            headers=headers,
            timeout=10,
        )
        if not resp.ok:
            logger.warning(
                "Reminder send failed (%s) for chat %s: %s",
                resp.status_code,
                user_id,
                resp.text,
            )
    except Exception as e:  # pragma: no cover - защита от падения потока
        logger.warning("Exception while sending reminder to %s: %r", user_id, e)


def _format_global_reminder_text() -> str:
    # Текст, который ты присылал, с 🚀
    return (
        "Пора заняться привычками!🚀\n"
        "Зайдите в «Мои привычки» и отметьте выполненные."
    )


def _format_habit_reminder_text(habit_name: str) -> str:
    # И персональное напоминание по конкретной привычке
    return f"Напоминание по привычке «{habit_name}» — самое время выполнить её!🚀"


class ReminderScheduler:
    """
    Фоновый планировщик напоминаний.
    """

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ---------------- Публичные методы ----------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ReminderScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Reminder scheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Reminder scheduler stopped")

    # ---------------- Внутренние методы ----------------

    def _run(self) -> None:
        """
        Основной цикл.

        ВАЖНО: если REMINDER_TICK_SECONDS == 60, то цикл привязывается к
        началу минуты, чтобы напоминания приходили как можно ближе к `..:..:00`.
        """
        while not self._stop_event.is_set():
            start = time.time()
            try:
                self._tick()
            except Exception as e:  # pragma: no cover - защита от падения потока
                logger.exception("Error in reminder scheduler loop: %r", e)

            # --- Сон между тиками ---
            if config.REMINDER_TICK_SECONDS == 60:
                # Привязываемся к следующей "ровной" минуте по UTC.
                now_utc = datetime.now(timezone.utc)
                next_minute = (now_utc + timedelta(minutes=1)).replace(
                    second=0,
                    microsecond=0,
                )
                sleep_for = (next_minute - now_utc).total_seconds()
                # На всякий случай
                if sleep_for < 1.0:
                    sleep_for = 1.0
            else:
                elapsed = time.time() - start
                sleep_for = max(1.0, config.REMINDER_TICK_SECONDS - elapsed)

            if self._stop_event.wait(sleep_for):
                break

    def _tick(self) -> None:
        """
        Один проход планировщика: читаем все включённые напоминания и,
        если нужно, "стреляем".
        """
        reminders = storage.list_all_enabled_reminders()
        if not reminders:
            return

        # Кэш смещений часовых поясов, чтобы не дёргать БД для каждого напоминания
        tz_cache: Dict[int, int] = {}

        for row in reminders:
            reminder_id = row["id"]
            user_id = row["user_id"]
            habit_id = row["habit_id"]
            day_of_week = row["day_of_week"]  # 0 = Пн, 6 = Вс
            kind = row["kind"]
            time_str = row["time"]
            interval_minutes = row["interval_minutes"]

            # Часовой пояс пользователя
            if user_id not in tz_cache:
                tz_cache[user_id] = storage.get_user_timezone_offset(user_id)
            offset_minutes = tz_cache[user_id]

            user_now = _get_user_now(offset_minutes)

            # День недели: если в напоминании указан день,
            # то срабатываем только в этот день.
            if day_of_week is not None and user_now.weekday() != day_of_week:
                continue

            fire = False

            if kind == "fixed":
                # Ожидаем строку HH:MM
                if not time_str:
                    continue
                try:
                    hh, mm = map(int, time_str.split(":", 1))
                except Exception:
                    continue

                if user_now.hour == hh and user_now.minute == mm:
                    fire = True

            elif kind == "interval":
                # Интервальное напоминание "каждые N минут"
                if not interval_minutes or interval_minutes <= 0:
                    continue

                minutes_since_midnight = user_now.hour * 60 + user_now.minute
                if minutes_since_midnight % interval_minutes == 0:
                    fire = True

            if not fire:
                continue

            # --- Формируем текст напоминания ---
            if habit_id is None:
                text = _format_global_reminder_text()
            else:
                habit = storage.get_habit(habit_id)
                if habit is None:
                    continue
                text = _format_habit_reminder_text(habit["name"])

            logger.info(
                "Firing reminder id=%s chat=%s local_time=%s kind=%s",
                reminder_id,
                user_id,
                user_now.isoformat(timespec="seconds"),
                kind,
            )
            _send_message(self.bot_token, user_id, text)
