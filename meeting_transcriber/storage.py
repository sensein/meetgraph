"""Local SQLite storage for meetings (transcript + structured summary).

The database lives in the platform's per-user app-data directory so a user's
content persists across runs and is private to their account.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "MeetGraph"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "MeetGraph"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "MeetGraph"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Meeting:
    id: int
    user: str
    title: str
    started_at: str
    ended_at: str
    summary_md: str | None
    created_at: str


class Store:
    """Thin SQLite wrapper over two separate databases.

    Content (one row per recorded meeting) lives in ``meetgraph.db``; user
    configuration and secrets (API keys, external-DB credentials) live in a
    *separate* ``meetgraph-config.db``. Keeping them apart means content can be
    backed up, shared, or wiped without touching credentials, and vice versa.
    """

    def __init__(
        self,
        path: str | os.PathLike | None = None,
        config_path: str | os.PathLike | None = None,
    ):
        self.path = str(path or (data_dir() / "meetgraph.db"))
        self.config_path = str(config_path or (data_dir() / "meetgraph-config.db"))
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _connect_config(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.config_path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS meetings (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user            TEXT,
                    title           TEXT,
                    started_at      TEXT,
                    ended_at        TEXT,
                    transcript_md   TEXT,
                    transcript_plain TEXT,
                    summary_md      TEXT,
                    summary_json    TEXT,
                    created_at      TEXT
                )
                """
            )
        with self._connect_config() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
        self._migrate_settings()
        # Both DBs may hold secrets — keep them readable only by the owner.
        for p in (self.path, self.config_path):
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass

    def _migrate_settings(self) -> None:
        """One-time copy of settings from the old combined DB into the config DB."""
        try:
            with self._connect_config() as cfg:
                if cfg.execute("SELECT COUNT(*) FROM settings").fetchone()[0]:
                    return  # config DB already populated
            with self._connect() as con:
                has = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
                ).fetchone()
                if not has:
                    return
                rows = con.execute("SELECT key, value FROM settings").fetchall()
            if rows:
                with self._connect_config() as cfg:
                    cfg.executemany(
                        "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                        [(r["key"], r["value"]) for r in rows],
                    )
        except sqlite3.Error:
            pass

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect_config() as con:
            row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect_config() as con:
            con.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def save_meeting(
        self,
        user: str,
        title: str,
        started_at: str,
        ended_at: str,
        transcript_md: str,
        transcript_plain: str,
        summary_md: str | None = None,
        summary_json: str | None = None,
    ) -> int:
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO meetings
                   (user, title, started_at, ended_at, transcript_md,
                    transcript_plain, summary_md, summary_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user, title, started_at, ended_at, transcript_md,
                 transcript_plain, summary_md, summary_json, datetime.now().isoformat(timespec="seconds")),
            )
            return int(cur.lastrowid)

    def update_summary(self, meeting_id: int, summary_md: str, summary_json: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE meetings SET summary_md = ?, summary_json = ? WHERE id = ?",
                (summary_md, summary_json, meeting_id),
            )

    _LIST_COLS = "id, user, title, started_at, ended_at, summary_md, created_at"

    def list_meetings(self, user: str | None = None, limit: int = 200) -> list[Meeting]:
        q = f"SELECT {self._LIST_COLS} FROM meetings"
        args: tuple = ()
        if user:
            q += " WHERE user = ?"
            args = (user,)
        q += " ORDER BY id DESC LIMIT ?"
        args = args + (limit,)
        with self._connect() as con:
            return [Meeting(**dict(r)) for r in con.execute(q, args).fetchall()]

    def search_meetings(self, query: str, limit: int = 200) -> list[Meeting]:
        """Full-text-ish search across title, transcript and summary."""
        if not query.strip():
            return self.list_meetings(limit=limit)
        like = f"%{query.strip()}%"
        q = (
            f"SELECT {self._LIST_COLS} FROM meetings "
            "WHERE title LIKE ? OR transcript_plain LIKE ? OR summary_md LIKE ? "
            "ORDER BY id DESC LIMIT ?"
        )
        with self._connect() as con:
            rows = con.execute(q, (like, like, like, limit)).fetchall()
            return [Meeting(**dict(r)) for r in rows]

    def get_meeting(self, meeting_id: int) -> dict | None:
        """Full record including transcript + summary bodies."""
        with self._connect() as con:
            row = con.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
            return dict(row) if row else None

    def delete_meeting(self, meeting_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
