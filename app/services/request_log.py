"""Simple request logging to SQLite for tracking errors and improving over time."""

import sqlite3
from datetime import datetime, timezone

from app.config import settings

_LOG_DB = None


def _get_log_db() -> sqlite3.Connection:
    global _LOG_DB
    if _LOG_DB is None:
        _LOG_DB = sqlite3.connect(settings.database_path)
        _LOG_DB.row_factory = sqlite3.Row
        _LOG_DB.execute("""
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                url TEXT NOT NULL,
                success INTEGER NOT NULL,
                title TEXT,
                ingredient_count INTEGER,
                warning_count INTEGER,
                warnings TEXT,
                error TEXT,
                duration_s REAL
            )
        """)
        _LOG_DB.commit()
    return _LOG_DB


def log_request(
    url: str,
    success: bool,
    title: str | None = None,
    ingredient_count: int | None = None,
    warning_count: int | None = None,
    warnings: str | None = None,
    error: str | None = None,
    duration_s: float | None = None,
):
    db = _get_log_db()
    db.execute(
        """
        INSERT INTO request_log
            (timestamp, url, success, title, ingredient_count, warning_count, warnings, error, duration_s)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            url,
            int(success),
            title,
            ingredient_count,
            warning_count,
            warnings,
            error,
            round(duration_s, 3) if duration_s else None,
        ),
    )
    db.commit()


def get_recent_logs(limit: int = 50) -> list[dict]:
    db = _get_log_db()
    cur = db.execute(
        "SELECT * FROM request_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def get_error_summary() -> list[dict]:
    """Get a summary of recent errors for debugging."""
    db = _get_log_db()
    cur = db.execute("""
        SELECT url, error, COUNT(*) as count, MAX(timestamp) as last_seen
        FROM request_log
        WHERE success = 0
        GROUP BY url, error
        ORDER BY count DESC
        LIMIT 50
    """)
    return [dict(row) for row in cur.fetchall()]


def get_warning_summary() -> list[dict]:
    """Get most common warnings to identify ingredients that need overrides."""
    db = _get_log_db()
    cur = db.execute("""
        SELECT warnings, COUNT(*) as count
        FROM request_log
        WHERE warning_count > 0 AND warnings IS NOT NULL
        GROUP BY warnings
        ORDER BY count DESC
        LIMIT 50
    """)
    return [dict(row) for row in cur.fetchall()]
