"""SQLite storage. Local only; one file; schema versioned with PRAGMA user_version."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

_MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
    CREATE TABLE safety_events (id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
        reason TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
    CREATE TABLE action_log (id INTEGER PRIMARY KEY, ts REAL NOT NULL, command_json TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT NOT NULL, risk INTEGER NOT NULL);
    CREATE TABLE interactions (id INTEGER PRIMARY KEY, ts REAL NOT NULL, app TEXT, element_key TEXT NOT NULL,
        control_type TEXT, action_kind TEXT NOT NULL, outcome TEXT NOT NULL, confidence REAL);
    CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL NOT NULL, kind TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'train', notes TEXT NOT NULL DEFAULT '');
    CREATE TABLE trials (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL, options_json TEXT NOT NULL, left_option TEXT NOT NULL, right_option TEXT NOT NULL,
        created_at REAL NOT NULL, features_json TEXT, prediction_json TEXT, locked_at REAL, prediction_hash TEXT,
        label TEXT, revealed_at REAL);
    CREATE TABLE model_versions (id INTEGER PRIMARY KEY, version INTEGER NOT NULL, created_at REAL NOT NULL,
        path TEXT NOT NULL, metadata_json TEXT NOT NULL);
    CREATE TABLE baseline (id INTEGER PRIMARY KEY CHECK (id = 1), updated_at REAL NOT NULL, json TEXT NOT NULL);
    """,
}

# Tables that hold personal (face / behaviour) data, wiped by delete_personal_data().
PERSONAL_TABLES = ["trials", "sessions", "model_versions", "baseline", "interactions", "action_log"]


class StorageError(RuntimeError):
    pass


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
        except sqlite3.Error as exc:
            raise StorageError(f"cannot open database {self.path}: {exc}") from exc

    def _migrate(self) -> None:
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise StorageError(f"database schema {current} is newer than this app ({SCHEMA_VERSION})")
        for v in range(current + 1, SCHEMA_VERSION + 1):
            self._conn.execute("BEGIN")
            try:
                for stmt in filter(str.strip, _MIGRATIONS[v].split(";")):
                    self._conn.execute(stmt)
                self._conn.execute(f"PRAGMA user_version = {v}")
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                self._conn.execute("ROLLBACK")
                raise

    # ---- generic helpers -------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                return self._conn.execute(sql, tuple(params))
            except sqlite3.Error as exc:
                raise StorageError(str(exc)) from exc

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def close(self) -> None:
        self._conn.close()

    # ---- settings ---------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self.query("SELECT value_json FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings(key, value_json) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json", (key, json.dumps(value)))

    def all_settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value_json"]) for r in self.query("SELECT * FROM settings")}

    # ---- logs ---------------------------------------------------------------------
    def log_safety_event(self, ts: float, kind: str, reason: str, detail: str = "") -> None:
        self.execute("INSERT INTO safety_events(ts, kind, reason, detail) VALUES(?,?,?,?)", (ts, kind, reason, detail))

    def log_action(self, command_json: str, status: str, reason: str, risk: int) -> None:
        self.execute("INSERT INTO action_log(ts, command_json, status, reason, risk) VALUES(?,?,?,?,?)",
                     (time.time(), command_json, status, reason, risk))

    def recent_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self.query("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,))]

    def log_interaction(self, app: str | None, element_key: str, control_type: str | None, action_kind: str,
                        outcome: str, confidence: float | None) -> None:
        self.execute("INSERT INTO interactions(ts, app, element_key, control_type, action_kind, outcome, confidence)"
                     " VALUES(?,?,?,?,?,?,?)", (time.time(), app, element_key, control_type, action_kind, outcome, confidence))

    # ---- privacy -------------------------------------------------------------------
    def delete_personal_data(self) -> dict[str, int]:
        """Complete deletion of personal data. Safety events and settings are kept (not personal)."""
        counts: dict[str, int] = {}
        for table in PERSONAL_TABLES:
            counts[table] = self.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                for table in PERSONAL_TABLES:
                    self._conn.execute(f"DELETE FROM {table}")
                self._conn.execute("COMMIT")
            except sqlite3.Error as exc:
                self._conn.execute("ROLLBACK")
                raise StorageError(str(exc)) from exc
        return counts
