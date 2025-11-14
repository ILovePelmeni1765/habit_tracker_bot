# storage.py

import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List, Tuple

import config

DB_PATH = config.DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    cur = conn.cursor()

    # Пользователи
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            tz_offset_minutes INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Привычки
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            daily_goal INTEGER NOT NULL,
            days_mask INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # Прогресс по дням
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            done_count INTEGER NOT NULL,
            UNIQUE(habit_id, date)
        )
        """
    )

    # Напоминания
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            habit_id INTEGER,
            day_of_week INTEGER,
            kind TEXT NOT NULL,
            time TEXT,
            interval_minutes INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # Состояние диалога
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            data TEXT
        )
        """
    )

    conn.commit()
    conn.close()


# -------- Пользователи / таймзона --------


def ensure_user(user_id: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (user_id, tz_offset_minutes) VALUES (?, ?)",
            (user_id, 0),
        )
    conn.commit()
    conn.close()


def get_user_timezone_offset(user_id: int) -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT tz_offset_minutes FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return 0
    return row["tz_offset_minutes"]


def set_user_timezone_offset(user_id: int, offset_minutes: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (user_id, tz_offset_minutes)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET tz_offset_minutes = excluded.tz_offset_minutes
        """,
        (user_id, offset_minutes),
    )
    conn.commit()
    conn.close()


# -------- Привычки --------


def create_habit(
    user_id: int, name: str, daily_goal: int, days_mask: int
) -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO habits (user_id, name, daily_goal, days_mask, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, name, daily_goal, days_mask, datetime.utcnow().isoformat()),
    )
    habit_id = cur.lastrowid
    conn.commit()
    conn.close()
    return habit_id


def list_habits(user_id: int) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM habits WHERE user_id = ? ORDER BY id",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_habit(habit_id: int) -> Optional[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM habits WHERE id = ?", (habit_id,))
    row = cur.fetchone()
    conn.close()
    return row


def update_habit(
    habit_id: int,
    name: Optional[str] = None,
    daily_goal: Optional[int] = None,
    days_mask: Optional[int] = None,
) -> None:
    fields = []
    params = []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if daily_goal is not None:
        fields.append("daily_goal = ?")
        params.append(daily_goal)
    if days_mask is not None:
        fields.append("days_mask = ?")
        params.append(days_mask)
    if not fields:
        return
    params.append(habit_id)
    query = "UPDATE habits SET " + ", ".join(fields) + " WHERE id = ?"

    conn = _connect()
    cur = conn.cursor()
    cur.execute(query, tuple(params))
    conn.commit()
    conn.close()


def delete_habit(habit_id: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM habit_progress WHERE habit_id = ?", (habit_id,))
    cur.execute("DELETE FROM reminders WHERE habit_id = ?", (habit_id,))
    cur.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()


# -------- Прогресс --------


def _get_progress_row(
    habit_id: int, date_str: str
) -> Optional[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM habit_progress WHERE habit_id = ? AND date = ?",
        (habit_id, date_str),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_progress(
    habit_id: int, date_str: str
) -> int:
    row = _get_progress_row(habit_id, date_str)
    if row is None:
        return 0
    return row["done_count"]


def set_progress(
    habit_id: int, date_str: str, done_count: int
) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO habit_progress (habit_id, date, done_count)
        VALUES (?, ?, ?)
        ON CONFLICT(habit_id, date) DO UPDATE SET done_count = excluded.done_count
        """,
        (habit_id, date_str, done_count),
    )
    conn.commit()
    conn.close()


def increment_progress(
    habit_id: int, date_str: str, delta: int, max_goal: int
) -> Tuple[int, int]:
    current = get_progress(habit_id, date_str)
    new_val = current + delta
    if new_val > max_goal:
        new_val = max_goal
    set_progress(habit_id, date_str, new_val)
    return new_val, max_goal


def get_progress_for_period(
    habit_id: int, start_date: date, end_date: date
) -> Dict[str, int]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date, done_count
        FROM habit_progress
        WHERE habit_id = ? AND date BETWEEN ? AND ?
        """,
        (
            habit_id,
            start_date.isoformat(),
            end_date.isoformat(),
        ),
    )
    rows = cur.fetchall()
    conn.close()
    result = {row["date"]: row["done_count"] for row in rows}
    d = start_date
    while d <= end_date:
        ds = d.isoformat()
        if ds not in result:
            result[ds] = 0
        d += timedelta(days=1)
    return result


# -------- Состояние диалога --------


def get_state(user_id: int) -> Tuple[str, Dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT state, data FROM user_states WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return "idle", {}
    data = json.loads(row["data"]) if row["data"] else {}
    return row["state"], data


def set_state(
    user_id: int, state: str, data: Optional[Dict[str, Any]] = None
) -> None:
    if data is None:
        data = {}
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_states (user_id, state, data)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET state = excluded.state, data = excluded.data
        """,
        (user_id, state, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def clear_state(user_id: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# -------- Напоминания --------


def upsert_reminder(
    user_id: int,
    habit_id: Optional[int],
    day_of_week: Optional[int],
    kind: str,
    time_str: Optional[str] = None,
    interval_minutes: Optional[int] = None,
) -> None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        DELETE FROM reminders
        WHERE user_id = ?
          AND (habit_id IS ? OR habit_id = ?)
          AND (day_of_week IS ? OR day_of_week = ?)
        """,
        (user_id, habit_id, habit_id, day_of_week, day_of_week),
    )

    cur.execute(
        """
        INSERT INTO reminders (user_id, habit_id, day_of_week, kind, time, interval_minutes, enabled)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (user_id, habit_id, day_of_week, kind, time_str, interval_minutes),
    )

    conn.commit()
    conn.close()


def disable_reminder(
    user_id: int, habit_id: Optional[int], day_of_week: Optional[int]
) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM reminders
        WHERE user_id = ?
          AND (habit_id IS ? OR habit_id = ?)
          AND (day_of_week IS ? OR day_of_week = ?)
        """,
        (user_id, habit_id, habit_id, day_of_week, day_of_week),
    )
    conn.commit()
    conn.close()


def list_habit_reminders(habit_id: int) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM reminders
        WHERE habit_id = ?
        ORDER BY day_of_week
        """,
        (habit_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_global_reminders(user_id: int) -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM reminders
        WHERE user_id = ? AND habit_id IS NULL
        ORDER BY day_of_week
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_all_enabled_reminders() -> List[sqlite3.Row]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM reminders
        WHERE enabled = 1
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows
