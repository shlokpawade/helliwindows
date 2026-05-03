"""
scheduler.py – SQLite-backed persistent reminder store.

Replaces the in-memory _ReminderStore in actions/local.py so reminders
survive assistant restarts.  On startup, reminders whose fire time has
already passed are spoken immediately via fire_overdue().
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import NamedTuple

from config import REMINDERS_DB
from utils import logger, speak


class Reminder(NamedTuple):
    id: int
    task: str
    fire_at: float   # Unix timestamp (time.time() + total_seconds)
    label: str       # human-readable duration string


class ReminderStore:
    """Thread-safe SQLite-backed reminder store."""

    def __init__(self, db_path: Path = REMINDERS_DB) -> None:
        self._db = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                task    TEXT    NOT NULL,
                fire_at REAL    NOT NULL,
                label   TEXT    NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, task: str, total_seconds: int, duration_label: str) -> Reminder:
        fire_at = time.time() + total_seconds
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO reminders (task, fire_at, label) VALUES (?, ?, ?)",
                (task, fire_at, duration_label),
            )
            self._conn.commit()
            rid = cur.lastrowid
        return Reminder(id=rid, task=task, fire_at=fire_at, label=duration_label)

    def remove(self, rid: int) -> bool:
        """Delete reminder by ID; returns True if it existed."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
            self._conn.commit()
            return cur.rowcount > 0

    def list_all(self) -> list[Reminder]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, task, fire_at, label FROM reminders ORDER BY fire_at"
            ).fetchall()
        return [Reminder(id=r[0], task=r[1], fire_at=r[2], label=r[3]) for r in rows]

    def cancel_by_task(self, fragment: str) -> int:
        """Cancel all reminders whose task contains *fragment*; returns count."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM reminders WHERE LOWER(task) LIKE ?",
                (f"%{fragment.lower()}%",),
            )
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # Startup: fire overdue reminders
    # ------------------------------------------------------------------

    def fire_overdue(self) -> None:
        """Speak any reminders whose fire_at time is in the past."""
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, task FROM reminders WHERE fire_at <= ?", (now,)
            ).fetchall()
            if rows:
                placeholders = ",".join("?" * len(rows))
                self._conn.execute(
                    f"DELETE FROM reminders WHERE id IN ({placeholders})",
                    [r[0] for r in rows],
                )
                self._conn.commit()
        for rid, task in rows:
            logger.info("Firing overdue reminder #%d: '%s'", rid, task)
            speak(f"Missed reminder! {task}.")


# Module-level singleton reused by LocalActions and at startup.
reminder_store = ReminderStore()
