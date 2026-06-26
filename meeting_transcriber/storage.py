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
    team_id: str | None = None


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
                    created_at      TEXT,
                    team_id         TEXT,
                    edited_by       TEXT,
                    edited_at       TEXT
                )
                """
            )
            # Notes - personal or team jottings authored directly (no transcript).
            # team_id NULL => personal; setting it shares the note to that team.
            # summary_json holds the same enrichment shape as a meeting summary
            # (key_terms / topics / publications / research_gaps).
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user            TEXT,
                    title           TEXT,
                    body_md         TEXT,
                    tags            TEXT,
                    summary_json    TEXT,
                    team_id         TEXT,
                    about_meeting_id INTEGER,
                    author_name     TEXT,
                    author_email    TEXT,
                    created_at      TEXT,
                    updated_at      TEXT,
                    edited_by       TEXT,
                    edited_at       TEXT
                )
                """
            )
            # Background enrichment jobs for notes (key-term/topic extraction,
            # literature) - mirrors meeting_jobs so status shows and resumes.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS note_jobs (
                    note_id     INTEGER,
                    stage       TEXT,
                    status      TEXT,
                    updated_at  TEXT,
                    PRIMARY KEY (note_id, stage)
                )
                """
            )
            # Links between meetings discovered by the cross-link agent.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_links (
                    meeting_id  INTEGER,
                    related_id  INTEGER,
                    relation    TEXT,
                    reason      TEXT,
                    PRIMARY KEY (meeting_id, related_id)
                )
                """
            )
            # Delivery state - which meetings were already sent to which destination,
            # so bulk send/sync can skip what's already delivered.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_state (
                    meeting_id   INTEGER,
                    destination  TEXT,
                    ts           TEXT,
                    PRIMARY KEY (meeting_id, destination)
                )
                """
            )
            # Background enrichment jobs per meeting (cross-linking, literature...),
            # so processing can show status and resume if interrupted.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS meeting_jobs (
                    meeting_id  INTEGER,
                    stage       TEXT,
                    status      TEXT,
                    updated_at  TEXT,
                    PRIMARY KEY (meeting_id, stage)
                )
                """
            )
            # Team keys this user has generated (for viewing / revoking).
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS team_keys (
                    key_id      TEXT PRIMARY KEY,
                    label       TEXT,
                    team_id     TEXT,
                    team_name   TEXT,
                    key         TEXT,
                    created_at  TEXT,
                    revoked     INTEGER DEFAULT 0
                )
                """
            )
            # Audit log - who did what (create/edit/delete/sync), kept for accountability.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts           TEXT,
                    team_id      TEXT,
                    actor_name   TEXT,
                    actor_email  TEXT,
                    action       TEXT,
                    target_id    INTEGER,
                    detail       TEXT
                )
                """
            )
            # Add newer columns to pre-existing databases.
            cols = {r["name"] for r in con.execute("PRAGMA table_info(meetings)").fetchall()}
            if "team_id" not in cols:
                con.execute("ALTER TABLE meetings ADD COLUMN team_id TEXT")
            if "edited_by" not in cols:
                con.execute("ALTER TABLE meetings ADD COLUMN edited_by TEXT")
            if "edited_at" not in cols:
                con.execute("ALTER TABLE meetings ADD COLUMN edited_at TEXT")
        with self._connect_config() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            # Teams this user belongs to. A user can join several teams (each an
            # isolated shared scope) and switch the active one. The full key is
            # kept so switching re-applies that team's shared-DB connection.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS team_memberships (
                    team_id    TEXT PRIMARY KEY,
                    team_name  TEXT,
                    key_id     TEXT,
                    key        TEXT,
                    joined_at  TEXT
                )
                """
            )
            # state: 'active' | 'left' | 'revoked'. access_until caps read-only
            # access to the team's notes at the moment of leaving/revocation.
            mcols = {r["name"] for r in con.execute("PRAGMA table_info(team_memberships)").fetchall()}
            if "state" not in mcols:
                con.execute("ALTER TABLE team_memberships ADD COLUMN state TEXT DEFAULT 'active'")
            if "access_until" not in mcols:
                con.execute("ALTER TABLE team_memberships ADD COLUMN access_until TEXT")
        self._migrate_settings()
        # Both DBs may hold secrets - keep them readable only by the owner.
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
        team_id: str | None = None,
    ) -> int:
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO meetings
                   (user, title, started_at, ended_at, transcript_md,
                    transcript_plain, summary_md, summary_json, created_at, team_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user, title, started_at, ended_at, transcript_md,
                 transcript_plain, summary_md, summary_json,
                 datetime.now().isoformat(timespec="seconds"), team_id),
            )
            return int(cur.lastrowid)

    def set_links(self, meeting_id: int, links: list[dict]) -> None:
        """Replace the cross-meeting links for a meeting. links: {related_id, relation, reason}."""
        with self._connect() as con:
            con.execute("DELETE FROM meeting_links WHERE meeting_id = ?", (meeting_id,))
            con.executemany(
                "INSERT OR REPLACE INTO meeting_links(meeting_id, related_id, relation, reason) "
                "VALUES (?, ?, ?, ?)",
                [(meeting_id, l["related_id"], l.get("relation"), l.get("reason")) for l in links],
            )

    def get_links(self, meeting_id: int) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT related_id, relation, reason FROM meeting_links WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_sent(self, meeting_id: int, destination: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO delivery_state(meeting_id, destination, ts) VALUES (?, ?, ?)",
                (meeting_id, destination, datetime.now().isoformat(timespec="seconds")),
            )

    def sent_destinations(self, meeting_id: int) -> set[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT destination FROM delivery_state WHERE meeting_id = ?", (meeting_id,)
            ).fetchall()
            return {r["destination"] for r in rows}

    def is_sent(self, meeting_id: int, destination: str) -> bool:
        with self._connect() as con:
            return con.execute(
                "SELECT 1 FROM delivery_state WHERE meeting_id = ? AND destination = ?",
                (meeting_id, destination),
            ).fetchone() is not None

    def add_team_key(self, key_id: str, label: str, team_id: str, team_name: str,
                     key: str, created_at: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO team_keys(key_id, label, team_id, team_name, key, created_at, revoked) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (key_id, label, team_id, team_name, key, created_at),
            )

    def list_team_keys(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT key_id, label, team_id, team_name, key, created_at, revoked "
                "FROM team_keys ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def set_key_revoked(self, key_id: str, revoked: bool = True) -> None:
        with self._connect() as con:
            con.execute("UPDATE team_keys SET revoked = ? WHERE key_id = ?",
                        (1 if revoked else 0, key_id))

    # ----- team memberships (the teams this user can switch between) -----
    def add_membership(self, team_id: str, team_name: str, key_id: str, key: str,
                       joined_at: str) -> None:
        with self._connect_config() as con:
            # Re-joining reactivates and clears any prior access cap.
            con.execute(
                "INSERT INTO team_memberships(team_id, team_name, key_id, key, joined_at, "
                "state, access_until) VALUES (?, ?, ?, ?, ?, 'active', NULL) "
                "ON CONFLICT(team_id) DO UPDATE SET team_name=excluded.team_name, "
                "key_id=excluded.key_id, key=excluded.key, state='active', access_until=NULL",
                (team_id, team_name, key_id, key, joined_at),
            )

    _MEMBERSHIP_COLS = "team_id, team_name, key_id, key, joined_at, state, access_until"

    def list_memberships(self) -> list[dict]:
        with self._connect_config() as con:
            rows = con.execute(
                f"SELECT {self._MEMBERSHIP_COLS} FROM team_memberships ORDER BY joined_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_membership(self, team_id: str) -> dict | None:
        with self._connect_config() as con:
            row = con.execute(
                f"SELECT {self._MEMBERSHIP_COLS} FROM team_memberships WHERE team_id = ?",
                (team_id,)
            ).fetchone()
            return dict(row) if row else None

    def set_membership_state(self, team_id: str, state: str, access_until: str | None) -> None:
        """Mark a membership 'left'/'revoked' and cap read-only access at a time."""
        with self._connect_config() as con:
            con.execute(
                "UPDATE team_memberships SET state = ?, access_until = ? WHERE team_id = ?",
                (state, access_until, team_id),
            )

    def remove_membership(self, team_id: str) -> None:
        with self._connect_config() as con:
            con.execute("DELETE FROM team_memberships WHERE team_id = ?", (team_id,))

    def mark_job(self, meeting_id: int, stage: str, status: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO meeting_jobs(meeting_id, stage, status, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(meeting_id, stage) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
                (meeting_id, stage, status, datetime.now().isoformat(timespec="seconds")),
            )

    def jobs_for(self, meeting_id: int) -> dict:
        with self._connect() as con:
            rows = con.execute(
                "SELECT stage, status FROM meeting_jobs WHERE meeting_id = ?", (meeting_id,)
            ).fetchall()
            return {r["stage"]: r["status"] for r in rows}

    def pending_jobs(self) -> list[tuple]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT meeting_id, stage FROM meeting_jobs WHERE status = 'pending'"
            ).fetchall()
            return [(r["meeting_id"], r["stage"]) for r in rows]

    def log_action(
        self,
        action: str,
        actor_name: str = "",
        actor_email: str = "",
        team_id: str | None = None,
        target_id: int | None = None,
        detail: str | None = None,
    ) -> dict:
        """Append an audit entry (who did what, when) and return it."""
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "team_id": team_id, "actor_name": actor_name, "actor_email": actor_email,
            "action": action, "target_id": target_id, "detail": detail,
        }
        with self._connect() as con:
            con.execute(
                "INSERT INTO audit_log(ts, team_id, actor_name, actor_email, action, target_id, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry["ts"], team_id, actor_name, actor_email, action, target_id, detail),
            )
        return entry

    def team_emails(self, team_id: str | None = None) -> list[str]:
        """Distinct member emails seen in the audit log (optionally for a team)."""
        with self._connect() as con:
            if team_id:
                rows = con.execute(
                    "SELECT DISTINCT actor_email FROM audit_log WHERE team_id = ? AND actor_email <> ''",
                    (team_id,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT DISTINCT actor_email FROM audit_log WHERE actor_email <> ''"
                ).fetchall()
            return [r["actor_email"] for r in rows if r["actor_email"]]

    def list_audit(self, limit: int = 500) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT ts, team_id, actor_name, actor_email, action, target_id, detail "
                "FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def rename_meeting(self, meeting_id: int, title: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE meetings SET title = ? WHERE id = ?", (title, meeting_id))

    def set_summary_edited(self, meeting_id: int, summary_md: str,
                           edited_by: str, edited_at: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE meetings SET summary_md = ?, edited_by = ?, edited_at = ? WHERE id = ?",
                (summary_md, edited_by, edited_at, meeting_id),
            )

    def update_summary(self, meeting_id: int, summary_md: str, summary_json: str) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE meetings SET summary_md = ?, summary_json = ? WHERE id = ?",
                (summary_md, summary_json, meeting_id),
            )

    _LIST_COLS = "id, user, title, started_at, ended_at, summary_md, created_at, team_id"

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

    # ------------------------------------------------------------------ notes
    _NOTE_LIST_COLS = ("id, user, title, tags, team_id, about_meeting_id, "
                       "author_name, author_email, created_at, updated_at, edited_by, edited_at")

    def save_note(
        self,
        user: str,
        title: str,
        body_md: str,
        tags: str = "",
        team_id: str | None = None,
        about_meeting_id: int | None = None,
        author_name: str = "",
        author_email: str = "",
        summary_json: str | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            cur = con.execute(
                """INSERT INTO notes
                   (user, title, body_md, tags, summary_json, team_id, about_meeting_id,
                    author_name, author_email, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user, title, body_md, tags, summary_json, team_id, about_meeting_id,
                 author_name, author_email, now, now),
            )
            return int(cur.lastrowid)

    def update_note(
        self,
        note_id: int,
        title: str,
        body_md: str,
        tags: str = "",
        about_meeting_id: int | None = None,
        edited_by: str = "",
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute(
                "UPDATE notes SET title = ?, body_md = ?, tags = ?, about_meeting_id = ?, "
                "updated_at = ?, edited_by = ?, edited_at = ? WHERE id = ?",
                (title, body_md, tags, about_meeting_id, now, edited_by, now, note_id),
            )

    def set_note_enrichment(self, note_id: int, summary_json: str) -> None:
        with self._connect() as con:
            con.execute("UPDATE notes SET summary_json = ? WHERE id = ?", (summary_json, note_id))

    def set_note_team(self, note_id: int, team_id: str | None) -> None:
        """Share a personal note to a team (or move it back to personal)."""
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("UPDATE notes SET team_id = ?, updated_at = ? WHERE id = ?",
                        (team_id, now, note_id))

    def list_notes(self, user: str | None = None, limit: int = 500) -> list[dict]:
        q = f"SELECT {self._NOTE_LIST_COLS} FROM notes"
        args: tuple = ()
        if user:
            q += " WHERE user = ?"
            args = (user,)
        q += " ORDER BY id DESC LIMIT ?"
        args = args + (limit,)
        with self._connect() as con:
            return [dict(r) for r in con.execute(q, args).fetchall()]

    def search_notes(self, query: str, limit: int = 500) -> list[dict]:
        if not query.strip():
            return self.list_notes(limit=limit)
        like = f"%{query.strip()}%"
        q = (f"SELECT {self._NOTE_LIST_COLS} FROM notes "
             "WHERE title LIKE ? OR body_md LIKE ? OR tags LIKE ? "
             "ORDER BY id DESC LIMIT ?")
        with self._connect() as con:
            return [dict(r) for r in con.execute(q, (like, like, like, limit)).fetchall()]

    def get_note(self, note_id: int) -> dict | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            return dict(row) if row else None

    def delete_note(self, note_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            con.execute("DELETE FROM note_jobs WHERE note_id = ?", (note_id,))

    def mark_note_job(self, note_id: int, stage: str, status: str) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO note_jobs(note_id, stage, status, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(note_id, stage) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
                (note_id, stage, status, datetime.now().isoformat(timespec="seconds")),
            )

    def note_jobs_for(self, note_id: int) -> dict:
        with self._connect() as con:
            rows = con.execute(
                "SELECT stage, status FROM note_jobs WHERE note_id = ?", (note_id,)
            ).fetchall()
            return {r["stage"]: r["status"] for r in rows}

    def pending_note_jobs(self) -> list[tuple]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT note_id, stage FROM note_jobs WHERE status = 'pending'"
            ).fetchall()
            return [(r["note_id"], r["stage"]) for r in rows]
