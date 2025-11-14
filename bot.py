# bot.py

from datetime import datetime, timedelta, date
import re
from typing import List, Dict, Any, Tuple, Optional

from maxgram import Bot
from maxgram.keyboards import InlineKeyboard

import config
import storage

DAYS = [
    ("Пн", 0),
    ("Вт", 1),
    ("Ср", 2),
    ("Чт", 3),
    ("Пт", 4),
    ("Сб", 5),
    ("Вс", 6),
]

bot = Bot(config.BOT_TOKEN)


# ===== ВСПОМОГАТЕЛЬНОЕ =====

def _days_mask_to_list(mask: int) -> List[int]:
    return [d for _, d in DAYS if mask & (1 << d)]


def _list_to_days_mask(days: List[int]) -> int:
    mask = 0
    for d in days:
        mask |= 1 << d
    return mask


def _format_days(mask: int) -> str:
    if mask == 0:
        return "нет"
    labels = [label for label, d in DAYS if mask & (1 << d)]
    return ", ".join(labels)


def _get_user_date(user_id: int) -> date:
    offset_minutes = storage.get_user_timezone_offset(user_id)
    now_utc = datetime.utcnow()
    local = now_utc + timedelta(minutes=offset_minutes)
    return local.date()


def _make_progress_bar(done: int, goal: int) -> str:
    if goal <= 0:
        return ""

    # длина прогресс-бара: если цель <= 10 — столько же кубиков,
    # если > 10 — фиксированно 10
    bar_length = goal if goal <= 10 else 10

    ratio = done / goal
    filled = int(round(ratio * bar_length))
    filled = max(0, min(bar_length, filled))

    # 🟩 — выполнено, ⬜ — осталось
    return "🟩" * filled + "⬜" * (bar_length - filled)



def _habit_card_text(habit_row, user_id: int) -> str:
    today = _get_user_date(user_id)
    date_str = today.isoformat()
    done = storage.get_progress(habit_row["id"], date_str)
    goal = habit_row["daily_goal"]
    mask = habit_row["days_mask"]
    planned_today = "да" if mask & (1 << today.weekday()) else "нет"
    bar = _make_progress_bar(done, goal)
    text = (
        f"{habit_row['name']}\n"
        f"Цель на день: {goal}\n"
        f"Запланировано на сегодня: {planned_today}\n"
        f"Дни: {_format_days(mask)}\n"
        f"Выполнено сегодня: {done}/{goal}\n"
        f"{bar}"
    )
    return text


def _main_menu_keyboard() -> InlineKeyboard:
    return InlineKeyboard(
        [
            {"text": "➕ Добавить привычку", "callback": "menu:add_habit"},
        ],
        [
            {"text": "📋 Мои привычки", "callback": "menu:my_habits"},
        ],
        [
            {"text": "📊 Статистика", "callback": "menu:stats"},
        ],
        [
            {"text": "🔔 Глобальные напоминания", "callback": "menu:global_reminders"},
        ],
        [
            {"text": "🌏 Часовые пояса", "callback": "menu:timezones"},
        ],
    )


def _weekdays_keyboard(selected: List[int], mode: str) -> InlineKeyboard:
    """
    mode:
      - 'add'
      - 'edit:<habit_id>'
      - 'remind:<habit_id>'
      - 'global_remind'
    """
    rows = []
    for i in range(0, len(DAYS), 3):
        row = []
        for label, d in DAYS[i:i + 3]:
            mark = "✅" if d in selected else "⚪"
            row.append(
                {
                    "text": f"{mark} {label}",
                    "callback": f"days:{mode}:{d}",
                }
            )
        rows.append(row)

    rows.append(
        [
            {
                "text": "Каждый день",
                "callback": f"days:{mode}:all",
            }
        ]
    )

    if mode.startswith("add") or mode.startswith("edit"):
        rows.append(
            [
                {"text": "Готово", "callback": f"days:{mode}:done"},
                {"text": "Отмена", "callback": "days:cancel"},
            ]
        )

    return InlineKeyboard(*rows)


def _habit_menu_keyboard(habit_id: int, include_back: bool = False) -> InlineKeyboard:
    rows = [
        [
            {"text": "✅ Сделано", "callback": f"habit:done:{habit_id}"},
        ],
        [
            {"text": "🖊️ Редактировать", "callback": f"habit:edit:{habit_id}"},
        ],
        [
            {"text": "🔔 Напоминания по дням", "callback": f"habit:reminders:{habit_id}"},
        ],
        [
            {"text": "🗑️ Удалить", "callback": f"habit:delete_confirm:{habit_id}"},
        ],
    ]
    if include_back:
        rows.append(
            [
                {"text": "Назад", "callback": "menu:my_habits"},
            ]
        )
    return InlineKeyboard(*rows)


def _edit_menu_keyboard(habit_id: int) -> InlineKeyboard:
    return InlineKeyboard(
        [
            {"text": "Название", "callback": f"edit:name:{habit_id}"},
        ],
        [
            {"text": "Цель на день", "callback": f"edit:goal:{habit_id}"},
        ],
        [
            {"text": "Дни недели", "callback": f"edit:days:{habit_id}"},
        ],
        [
            {"text": "Назад", "callback": f"habit:open:{habit_id}"},
        ],
    )


def _time_menu_keyboard(mode: str) -> InlineKeyboard:
    """
    mode:
      - 'habit:<habit_id>:<day>'
      - 'global:<day>'
    """
    return InlineKeyboard(
        [
            {"text": "08:00", "callback": f"time:{mode}:08:00"},
            {"text": "12:00", "callback": f"time:{mode}:12:00"},
        ],
        [
            {"text": "18:00", "callback": f"time:{mode}:18:00"},
        ],
        [
            {"text": "Каждые 3 часа", "callback": f"time:{mode}:every3h"},
        ],
        [
            {"text": "Вручную", "callback": f"time:{mode}:manual"},
        ],
        [
            {"text": "Отключить", "callback": f"time:{mode}:off"},
        ],
        [
            {"text": "Назад", "callback": "time:back"},
        ],
    )


def _stats_period_keyboard() -> InlineKeyboard:
    return InlineKeyboard(
        [
            {"text": "За день", "callback": "stats:period:day"},
        ],
        [
            {"text": "За неделю", "callback": "stats:period:week"},
        ],
        [
            {"text": "За месяц", "callback": "stats:period:month"},
        ],
        [
            {"text": "Назад", "callback": "menu:main"},
        ],
    )


def _timezones_keyboard() -> InlineKeyboard:
    rows = []
    for name, offset in config.TIMEZONES:
        rows.append(
            [
                {
                    "text": name,
                    "callback": f"tz:set:{offset}",
                }
            ]
        )
    rows.append(
        [
            {"text": "Назад", "callback": "menu:main"},
        ]
    )
    return InlineKeyboard(*rows)


def _parse_interval(text: str) -> Optional[int]:
    """
    Парсим:
      - "21:15" -> None (это время, не интервал)
      - "каждые 2 часа"
      - "каждые 1 час 30 минут"
      - "каждые 5 минут"
      - "каждые 2 ч", "каждые 10 мин", "каждые 1 минуту" и т.п.
    """
    t = text.strip().lower()
    # Если это похоже на время, а не интервал — выходим
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        return None
    if not t.startswith("каждые"):
        return None

    t = t.replace("каждые", "", 1).strip()

    hours = 0
    minutes = 0

    # часы: час, часа, часов, ч, ч.
    m = re.search(r"(\d+)\s*(?:час(?:ов|а)?|ч\.?)", t)
    if m:
        hours = int(m.group(1))

    # минуты: минута, минуты, минуту, минут, мин, мин., м, м.
    m = re.search(r"(\d+)\s*(?:минут(?:а|ы|у)?|мин\.?|м\.?)", t)
    if m:
        minutes = int(m.group(1))

    if hours == 0 and minutes == 0:
        return None

    return hours * 60 + minutes


# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====

@bot.on("bot_started")
def on_bot_started(context):
    message = (
        "Привет! 👋 Я — твой персональный трекер привычек! 💪\n"
        "Со мной ты сможешь легко и с удовольствием выработать полезные привычки "
        "и двигаться к своим целям каждый день! 🚀"
    )
    context.reply(message, keyboard=_main_menu_keyboard())


@bot.command("start")
def on_start_command(context):
    message = (
        "Привет! 👋 Я — твой персональный трекер привычек! 💪\n"
        "Со мной ты сможешь легко и с удовольствием выработать полезные привычки "
        "и двигаться к своим целям каждый день! 🚀"
    )
    context.reply(message, keyboard=_main_menu_keyboard())


@bot.on("message_created")
def on_message_created(context):
    msg = context.message
    if not msg or not msg.get("body"):
        return
    body = msg["body"]
    text = (body.get("text") or "").strip()
    if not text:
        return

    # Команды обрабатывает @bot.command
    if text.startswith("/"):
        return

    user_id = msg["sender"]["user_id"]
    storage.ensure_user(user_id)
    state, data = storage.get_state(user_id)

    # ===== ДОБАВЛЕНИЕ ПРИВЫЧКИ: НАЗВАНИЕ =====
    if state == "adding_habit_name":
        data["name"] = text
        storage.set_state(user_id, "adding_habit_goal", data)
        context.reply("🔢 Введите количество повторений за день (целое число > 0):")
        return

    # ===== ДОБАВЛЕНИЕ ПРИВЫЧКИ: ЦЕЛЬ =====
    if state == "adding_habit_goal":
        try:
            goal = int(text)
            if goal <= 0:
                raise ValueError()
        except ValueError:
            context.reply("Пожалуйста, введите целое число больше 0:")
            return
        data["goal"] = goal
        data["days"] = []
        storage.set_state(user_id, "adding_habit_days", data)
        context.reply(
            "Выберите дни недели для привычки:",
            keyboard=_weekdays_keyboard([], "add"),
        )
        return

    # ===== РЕДАКТИРОВАНИЕ НАЗВАНИЯ =====
    if state == "editing_name":
        habit_id = data.get("habit_id")
        if habit_id:
            storage.update_habit(habit_id, name=text)
        storage.clear_state(user_id)

        habit = storage.get_habit(habit_id)
        if habit:
            card_text = _habit_card_text(habit, user_id)
            context.reply(
                "Название обновлено.\n\n" + card_text,
                keyboard=_habit_menu_keyboard(habit_id, include_back=True),
            )
        else:
            context.reply("Название обновлено.")
        return

    # ===== РЕДАКТИРОВАНИЕ ЦЕЛИ =====
    if state == "editing_goal":
        habit_id = data.get("habit_id")
        try:
            goal = int(text)
            if goal <= 0:
                raise ValueError()
        except ValueError:
            context.reply(
                "Пожалуйста, введите целое число больше 0 или нажмите /start для выхода."
            )
            return

        if habit_id:
            storage.update_habit(habit_id, daily_goal=goal)
        storage.clear_state(user_id)

        habit = storage.get_habit(habit_id)
        if habit:
            card_text = _habit_card_text(habit, user_id)
            context.reply(
                "Цель обновлена.\n\n" + card_text,
                keyboard=_habit_menu_keyboard(habit_id, include_back=True),
            )
        else:
            context.reply("Цель обновлена.")
        return

    # ===== ВРУЧНУЮ ВРЕМЯ / ИНТЕРВАЛ НАПОМИНАНИЯ =====
    if state == "manual_reminder_time":
        kind_info = data.get("kind_info")
        if not kind_info:
            storage.clear_state(user_id)
            context.reply("Что-то пошло не так, попробуйте ещё раз.")
            return

        t = text.strip()
        time_match = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
        if time_match:
            hh = int(time_match.group(1))
            mm = int(time_match.group(2))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                context.reply("Неверное время. Пример: 21:15, попробуйте снова.")
                return
            time_str = f"{hh:02d}:{mm:02d}"
            habit_id = kind_info.get("habit_id")
            day = kind_info.get("day_of_week")
            is_global = kind_info.get("global", False)
            if is_global:
                storage.upsert_reminder(
                    user_id=user_id,
                    habit_id=None,
                    day_of_week=day,
                    kind="fixed",
                    time_str=time_str,
                    interval_minutes=None,
                )
                context.reply(
                    f"✅ Глобальное напоминание для {DAYS[day][0]} установлено на {time_str}."
                )
            else:
                storage.upsert_reminder(
                    user_id=user_id,
                    habit_id=habit_id,
                    day_of_week=day,
                    kind="fixed",
                    time_str=time_str,
                    interval_minutes=None,
                )
                context.reply(
                    f"✅ Напоминание для привычки на {DAYS[day][0]} установлено на {time_str}."
                )
            storage.clear_state(user_id)
            return

        interval = _parse_interval(text)
        if interval is None or interval <= 0:
            context.reply(
                "Не удалось распознать интервал. Примеры:\n"
                "21:15\n"
                "каждые 2 часа\n"
                "каждые 1 час 30 минут\n"
                "каждые 5 минут\n"
                "каждые 10 мин"
            )
            return

        habit_id = kind_info.get("habit_id")
        day = kind_info.get("day_of_week")
        is_global = kind_info.get("global", False)
        if is_global:
            storage.upsert_reminder(
                user_id=user_id,
                habit_id=None,
                day_of_week=day,
                kind="interval",
                time_str=None,
                interval_minutes=interval,
            )
            context.reply(
                f"✅ Глобальное напоминание для {DAYS[day][0]} установлено: каждые {interval} минут."
            )
        else:
            storage.upsert_reminder(
                user_id=user_id,
                habit_id=habit_id,
                day_of_week=day,
                kind="interval",
                time_str=None,
                interval_minutes=interval,
            )
            context.reply(
                f"✅ Напоминание для привычки на {DAYS[day][0]} установлено: каждые {interval} минут."
            )

        storage.clear_state(user_id)
        return

    # ===== ПО УМОЛЧАНИЮ =====
    context.reply("Я не понимаю это сообщение. Нажмите /start, чтобы открыть меню.")
    storage.clear_state(user_id)


# ===== ОБРАБОТЧИК КНОПОК =====

@bot.on("message_callback")
def on_callback(context):
    button = context.payload
    msg = context.message or {}

    # В message_callback message — это сообщение бота, получатель — пользователь.
    recipient = msg.get("recipient") or {}
    user_id = recipient.get("user_id") or recipient.get("chat_id")

    if not user_id:
        context.reply_callback("Ошибка: не удалось определить пользователя.", is_current=True)
        return

    storage.ensure_user(user_id)

    # --- главное меню ---
    if button == "menu:add_habit":
        storage.set_state(user_id, "adding_habit_name", {})
        context.reply_callback("✍️ Введите название привычки")
        return

    if button == "menu:my_habits":
        _show_my_habits(context, user_id)
        return

    if button == "menu:stats":
        context.reply_callback(
            "Выберите период статистики:",
            keyboard=_stats_period_keyboard(),
            is_current=True,
        )
        return

    if button == "menu:global_reminders":
        _show_global_reminders_menu(context, user_id)
        return

    if button == "menu:timezones":
        context.reply_callback(
            "Выберите ваш часовой пояс:",
            keyboard=_timezones_keyboard(),
            is_current=True,
        )
        return

    if button == "menu:main":
        context.reply_callback(
            "Главное меню",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        storage.clear_state(user_id)
        return

    # --- статистика ---
    if button.startswith("stats:period:"):
        period = button.split(":")[-1]
        _show_stats_choose_habit(context, user_id, period)
        return

    if button.startswith("stats:habit:"):
        _, _, period, habit_id_str = button.split(":")
        habit_id = int(habit_id_str)
        _show_stats_for_habit(context, user_id, habit_id, period)
        return

    # --- часовые пояса ---
    if button.startswith("tz:set:"):
        offset_hours = int(button.split(":")[-1])
        storage.set_user_timezone_offset(user_id, offset_hours * 60)
        context.reply_callback(
            f"✅ Часовой пояс установлен: UTC{offset_hours:+d}",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        return

    # --- привычка ---
    if button.startswith("habit:open:"):
        habit_id = int(button.split(":")[-1])
        _open_habit(context, user_id, habit_id)
        return

    if button.startswith("habit:done:"):
        habit_id = int(button.split(":")[-1])
        _habit_done(context, user_id, habit_id)
        return

    if button.startswith("habit:edit:"):
        habit_id = int(button.split(":")[-1])
        _open_edit_menu(context, habit_id)
        return

    if button.startswith("habit:reminders:"):
        habit_id = int(button.split(":")[-1])
        _open_habit_reminders(context, user_id, habit_id)
        return

    if button.startswith("habit:delete_confirm:"):
        habit_id = int(button.split(":")[-1])
        kb = InlineKeyboard(
            [
                {
                    "text": "Да, удалить",
                    "callback": f"habit:delete_yes:{habit_id}",
                }
            ],
            [
                {
                    "text": "Нет",
                    "callback": f"habit:open:{habit_id}",
                }
            ],
        )
        context.reply_callback(
            "Точно удалить привычку?",
            keyboard=kb,
            is_current=True,
        )
        return

    if button.startswith("habit:delete_yes:"):
        habit_id = int(button.split(":")[-1])
        storage.delete_habit(habit_id)
        context.reply_callback(
            "Привычка удалена.",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        return

    # --- редактирование ---
    if button.startswith("edit:name:"):
        habit_id = int(button.split(":")[-1])
        storage.set_state(user_id, "editing_name", {"habit_id": habit_id})
        context.reply_callback(
            "Введите новое название привычки:",
            keyboard=InlineKeyboard(
                [
                    {
                        "text": "Отмена",
                        "callback": f"edit:cancel:{habit_id}",
                    }
                ]
            ),
            is_current=True,
        )
        return

    if button.startswith("edit:goal:"):
        habit_id = int(button.split(":")[-1])
        storage.set_state(user_id, "editing_goal", {"habit_id": habit_id})
        context.reply_callback(
            "Введите новую цель (количество повторений за день):",
            keyboard=InlineKeyboard(
                [
                    {
                        "text": "Отмена",
                        "callback": f"edit:cancel:{habit_id}",
                    }
                ]
            ),
            is_current=True,
        )
        return

    if button.startswith("edit:cancel:"):
        habit_id = int(button.split(":")[-1])
        storage.clear_state(user_id)
        habit = storage.get_habit(habit_id)
        if habit:
            card_text = _habit_card_text(habit, user_id)
            context.reply_callback(
                "Изменение отменено.\n\n" + card_text,
                keyboard=_habit_menu_keyboard(habit_id, include_back=True),
                is_current=True,
            )
        else:
            context.reply_callback(
                "Изменение отменено.",
                keyboard=_main_menu_keyboard(),
                is_current=True,
            )
        return


    if button.startswith("edit:days:"):
        habit_id = int(button.split(":")[-1])
        habit = storage.get_habit(habit_id)
        if not habit:
            context.reply_callback("Привычка не найдена.")
            return
        mask = habit["days_mask"]
        selected = _days_mask_to_list(mask)
        storage.set_state(
            user_id,
            "editing_days",
            {"habit_id": habit_id, "days": selected},
        )
        context.reply_callback(
            "Измените дни недели:",
            keyboard=_weekdays_keyboard(selected, f"edit:{habit_id}"),
            is_current=True,
        )
        return

    # --- выбор дней ---
    if button.startswith("days:"):
        _handle_days_callback(context, user_id, button)
        return

    # --- выбор времени напоминаний ---
    if button.startswith("time:"):
        _handle_time_callback(context, user_id, button)
        return


# ===== ФУНКЦИИ ДЛЯ МЕНЮ / ПРИВЫЧЕК / НАПОМИНАНИЙ / СТАТИСТИКИ =====

def _show_my_habits(context, user_id: int):
    habits = storage.list_habits(user_id)
    if not habits:
        context.reply_callback(
            "У вас пока нет привычек. Нажмите «➕ Добавить привычку».",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        return
    rows = []
    for h in habits:
        rows.append(
            [
                {"text": h["name"], "callback": f"habit:open:{h['id']}"},
            ]
        )
    rows.append(
        [
            {"text": "Назад", "callback": "menu:main"},
        ]
    )
    context.reply_callback(
        "Ваши привычки:",
        keyboard=InlineKeyboard(*rows),
        is_current=True,
    )


def _open_habit(context, user_id: int, habit_id: int):
    habit = storage.get_habit(habit_id)
    if not habit:
        context.reply_callback("Привычка не найдена.")
        return
    text = _habit_card_text(habit, user_id)
    context.reply_callback(
        text,
        keyboard=_habit_menu_keyboard(habit_id, include_back=True),
        is_current=True,
    )


def _habit_done(context, user_id: int, habit_id: int):
    habit = storage.get_habit(habit_id)
    if not habit:
        context.reply_callback("Привычка не найдена.")
        return
    today = _get_user_date(user_id)
    date_str = today.isoformat()

    mask = habit["days_mask"]
    if not (mask & (1 << today.weekday())):
        context.reply_callback("Привычка запланирована на другой день!")
        return

    goal = habit["daily_goal"]
    current = storage.get_progress(habit_id, date_str)
    if current >= goal:
        context.reply_callback("Привычка выполнена на сегодня. Вы молодец!")
        return

    storage.increment_progress(habit_id, date_str, 1, goal)
    text = _habit_card_text(habit, user_id)
    context.reply_callback(
        text,
        keyboard=_habit_menu_keyboard(habit_id, include_back=True),
        is_current=True,
    )


def _open_edit_menu(context, habit_id: int):
    context.reply_callback(
        "Что хотите изменить?",
        keyboard=_edit_menu_keyboard(habit_id),
        is_current=True,
    )


def _open_habit_reminders(context, user_id: int, habit_id: int):
    habit = storage.get_habit(habit_id)
    if not habit:
        context.reply_callback("Привычка не найдена.")
        return

    text_lines = [f"🔔 Напоминания по дням для «{habit['name']}»:"]
    reminders = storage.list_habit_reminders(habit_id)
    by_day = {r["day_of_week"]: r for r in reminders}

    for label, d in DAYS:
        r = by_day.get(d)
        if r is None:
            status = "Откл."
        else:
            if r["kind"] == "fixed" and r["time"]:
                status = r["time"]
            elif r["kind"] == "interval" and r["interval_minutes"]:
                if r["interval_minutes"] == 180:
                    status = "Раз в 3 часа"
                else:
                    status = f"каждые {r['interval_minutes']} мин"
            else:
                status = "Откл."
        text_lines.append(f"{label}: {status}")

    rows = []
    for label, d in DAYS:
        rows.append(
            [
                {"text": label, "callback": f"days:remind:{habit_id}:{d}"},
            ]
        )
    rows.append(
        [
            {"text": "Назад", "callback": f"habit:open:{habit_id}"},
        ]
    )

    context.reply_callback(
        "\n".join(text_lines),
        keyboard=InlineKeyboard(*rows),
        is_current=True,
    )


def _show_global_reminders_menu(context, user_id: int):
    text_lines = ["Глобальные напоминания (сообщение «Пора заняться привычками!🚀»):"]
    reminders = storage.list_global_reminders(user_id)
    by_day = {r["day_of_week"]: r for r in reminders}

    for label, d in DAYS:
        r = by_day.get(d)
        if r is None:
            status = "Откл."
        else:
            if r["kind"] == "fixed" and r["time"]:
                status = r["time"]
            elif r["kind"] == "interval" and r["interval_minutes"]:
                if r["interval_minutes"] == 180:
                    status = "Раз в 3 часа"
                else:
                    status = f"каждые {r['interval_minutes']} мин"
            else:
                status = "Откл."
        text_lines.append(f"{label}: {status}")

    rows = []
    for label, d in DAYS:
        rows.append(
            [
                {"text": label, "callback": f"days:global_remind:{d}"},
            ]
        )
    rows.append(
        [
            {"text": "Назад", "callback": "menu:main"},
        ]
    )

    context.reply_callback(
        "\n".join(text_lines),
        keyboard=InlineKeyboard(*rows),
        is_current=True,
    )


def _handle_days_callback(context, user_id: int, button: str):
    parts = button.split(":")

    if button == "days:cancel":
        state, data = storage.get_state(user_id)
        storage.clear_state(user_id)

        # Если мы были в режиме редактирования дней существующей привычки —
        # возвращаемся в карточку этой привычки
        if state == "editing_days" and data.get("habit_id"):
            habit_id = data["habit_id"]
            habit = storage.get_habit(habit_id)
            if habit:
                card_text = _habit_card_text(habit, user_id)
                context.reply_callback(
                    "Изменение дней недели отменено.\n\n" + card_text,
                    keyboard=_habit_menu_keyboard(habit_id, include_back=True),
                    is_current=True,
                )
            else:
                context.reply_callback(
                    "Изменение дней недели отменено.",
                    keyboard=_main_menu_keyboard(),
                    is_current=True,
                )
        else:
            # Для добавления новой привычки и любых других состояний
            context.reply_callback(
                "Действие отменено.",
                keyboard=_main_menu_keyboard(),
                is_current=True,
            )
        return

    # --- добавление привычки ---
    if parts[1] == "add":
        _, _, target = parts
        state, data = storage.get_state(user_id)
        if state != "adding_habit_days":
            return
        days = data.get("days", [])
        if target == "all":
            days = [d for _, d in DAYS]
        elif target == "done":
            if not days:
                context.reply_callback(
                    "Вы не выбрали ни одного дня. Выберите хотя бы один.",
                    is_current=True,
                )
                return
            name = data["name"]
            goal = data["goal"]
            mask = _list_to_days_mask(days)
            habit_id = storage.create_habit(user_id, name, goal, mask)
            storage.clear_state(user_id)
            habit = storage.get_habit(habit_id)
            text = _habit_card_text(habit, user_id)
            context.reply_callback(
                "Привычка добавлена:\n\n" + text,
                keyboard=_habit_menu_keyboard(habit_id, include_back=True),
                is_current=True,
            )
            return
        else:
            day = int(target)
            if day in days:
                days.remove(day)
            else:
                days.append(day)

        data["days"] = days
        storage.set_state(user_id, "adding_habit_days", data)
        context.reply_callback(
            "Выберите дни недели для привычки:",
            keyboard=_weekdays_keyboard(days, "add"),
            is_current=True,
        )
        return

    # --- редактирование дней привычки ---
    if parts[1].startswith("edit"):
        _, mode, habit_id_str, target = parts
        habit_id = int(habit_id_str)
        state, data = storage.get_state(user_id)
        if state != "editing_days":
            return
        days = data.get("days", [])
        if target == "all":
            days = [d for _, d in DAYS]
        elif target == "done":
            if not days:
                context.reply_callback(
                    "Вы не выбрали ни одного дня. Выберите хотя бы один.",
                    is_current=True,
                )
                return
            mask = _list_to_days_mask(days)
            storage.update_habit(habit_id, days_mask=mask)
            storage.clear_state(user_id)
            habit = storage.get_habit(habit_id)
            text = _habit_card_text(habit, user_id)
            context.reply_callback(
                "Дни обновлены.\n\n" + text,
                keyboard=_habit_menu_keyboard(habit_id, include_back=True),
                is_current=True,
            )
            return
        else:
            day = int(target)
            if day in days:
                days.remove(day)
            else:
                days.append(day)
        data["days"] = days
        storage.set_state(user_id, "editing_days", data)
        context.reply_callback(
            "Измените дни недели:",
            keyboard=_weekdays_keyboard(days, f"edit:{habit_id}"),
            is_current=True,
        )
        return

    # --- напоминания для привычки ---
    if parts[1] == "remind":
        _, _, habit_id_str, day_str = parts
        habit_id = int(habit_id_str)
        day = int(day_str)
        mode = f"habit:{habit_id}:{day}"
        context.reply_callback(
            f"Выберите время напоминания для {DAYS[day][0]}:",
            keyboard=_time_menu_keyboard(mode),
            is_current=True,
        )
        return

    # --- глобальные напоминания ---
    if parts[1] == "global_remind":
        _, _, day_str = parts
        day = int(day_str)
        mode = f"global:{day}"
        context.reply_callback(
            f"Выберите время ГЛОБАЛЬНОГО напоминания для {DAYS[day][0]}:",
            keyboard=_time_menu_keyboard(mode),
            is_current=True,
        )
        return


def _handle_time_callback(context, user_id: int, button: str):
    if button == "time:back":
        context.reply_callback(
            "Главное меню:",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        storage.clear_state(user_id)
        return

    parts = button.split(":")
    # варианты:
    # time:habit:<habit_id>:<day>:action  (5 частей)
    # time:global:<day>:action            (4 части)
    if len(parts) < 4:
        return

    _, scope, *rest = parts
    if scope == "habit":
        if len(rest) < 3:
            return
        habit_id = int(rest[0])
        day = int(rest[1])
        action = rest[2]
        is_global = False
    elif scope == "global":
        if len(rest) < 2:
            return
        habit_id = None
        day = int(rest[0])
        action = rest[1]
        is_global = True
    else:
        return

    if action == "off":
        storage.disable_reminder(user_id, habit_id, day)
        if is_global:
            context.reply_callback(
                f"❌ Глобальное напоминание для {DAYS[day][0]} отключено.",
                is_current=True,
            )
        else:
            context.reply_callback(
                f"❌ Напоминание для привычки на {DAYS[day][0]} отключено.",
                is_current=True,
            )
        return

    if action == "every3h":
        storage.upsert_reminder(
            user_id=user_id,
            habit_id=habit_id,
            day_of_week=day,
            kind="interval",
            time_str=None,
            interval_minutes=180,
        )
        if is_global:
            context.reply_callback(
                f"✅ Глобальное напоминание для {DAYS[day][0]} установлено: раз в 3 часа.",
                is_current=True,
            )
        else:
            context.reply_callback(
                f"✅ Напоминание для привычки на {DAYS[day][0]} установлено: раз в 3 часа.",
                is_current=True,
            )
        return

    if action == "manual":
        storage.set_state(
            user_id,
            "manual_reminder_time",
            {
                "kind_info": {
                    "habit_id": habit_id,
                    "day_of_week": day,
                    "global": is_global,
                }
            },
        )
        context.reply_callback(
            "Пожалуйста укажите время/интервал отправления уведомления.\n"
            "Например: 21:15, каждые 2 часа, каждые 1 час 30 минут, каждые 5 минут, каждые 10 мин",
            is_current=True,
        )
        return

    # Остальное считаем временем HH:MM
    time_str = action
    storage.upsert_reminder(
        user_id=user_id,
        habit_id=habit_id,
        day_of_week=day,
        kind="fixed",
        time_str=time_str,
        interval_minutes=None,
    )
    if is_global:
        context.reply_callback(
            f"✅ Глобальное напоминание для {DAYS[day][0]} установлено на {time_str}.",
            is_current=True,
        )
    else:
        context.reply_callback(
            f"✅ Напоминание для привычки на {DAYS[day][0]} установлено на {time_str}.",
            is_current=True,
        )


def _show_stats_choose_habit(context, user_id: int, period: str):
    habits = storage.list_habits(user_id)
    if not habits:
        context.reply_callback(
            "У вас пока нет привычек.",
            keyboard=_main_menu_keyboard(),
            is_current=True,
        )
        return

    rows = []
    for h in habits:
        rows.append(
            [
                {"text": h["name"], "callback": f"stats:habit:{period}:{h['id']}"},
            ]
        )
    rows.append(
        [
            {"text": "Назад", "callback": "menu:stats"},
        ]
    )

    context.reply_callback(
        "Выберите привычку для просмотра статистики:",
        keyboard=InlineKeyboard(*rows),
        is_current=True,
    )


def _calc_period_dates(user_id: int, period: str) -> Tuple[date, date]:
    today = _get_user_date(user_id)
    if period == "day":
        return today, today
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    if period == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(days=1)
        return start, end
    return today, today


def _show_stats_for_habit(
    context, user_id: int, habit_id: int, period: str
):
    habit = storage.get_habit(habit_id)
    if not habit:
        context.reply_callback("Привычка не найдена.")
        return

    start_date, end_date = _calc_period_dates(user_id, period)
    progress = storage.get_progress_for_period(habit_id, start_date, end_date)
    goal = habit["daily_goal"]
    mask = habit["days_mask"]

    total_done = 0
    total_goal = 0

    d = start_date
    while d <= end_date:
        if mask & (1 << d.weekday()):
            total_goal += goal
            total_done += min(goal, progress[d.isoformat()])
        d += timedelta(days=1)

    percent = 0
    if total_goal > 0:
        percent = int(round(total_done / total_goal * 100))

    title = {
        "day": "Статистика за день",
        "week": "Статистика за неделю",
        "month": "Статистика за месяц",
    }.get(period, "Статистика")

    text = (
        f"{title} по привычке «{habit['name']}»\n\n"
        f"Период: {start_date.isoformat()} — {end_date.isoformat()}\n"
        f"Цель суммарно: {total_goal}\n"
        f"Выполнено: {total_done}\n"
        f"Процент: {percent}%"
    )

    context.reply_callback(
        text,
        keyboard=_stats_period_keyboard(),
        is_current=True,
    )
