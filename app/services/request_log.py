"""Simple request logging to SQLite for tracking errors and improving over time."""

import sqlite3
from datetime import datetime, timezone

from app.config import settings

_LOG_DB = None


def _get_log_db() -> sqlite3.Connection:
    global _LOG_DB
    if _LOG_DB is None:
        _LOG_DB = sqlite3.connect(settings.runtime_db_path)
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


def get_stats() -> dict:
    """Get traffic and usage statistics."""
    db = _get_log_db()

    # Overall counts
    cur = db.execute("""
        SELECT
            COUNT(*) as total_requests,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
            COUNT(DISTINCT url) as unique_urls,
            ROUND(AVG(CASE WHEN success = 1 THEN duration_s END), 3) as avg_duration_s,
            MIN(timestamp) as first_request,
            MAX(timestamp) as last_request
        FROM request_log
    """)
    overview = dict(cur.fetchone())

    # Requests per day
    cur = db.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as requests,
               SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
        FROM request_log
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        LIMIT 30
    """)
    daily = [dict(row) for row in cur.fetchall()]

    # Top recipes
    cur = db.execute("""
        SELECT url, title, COUNT(*) as hits, MAX(timestamp) as last_seen
        FROM request_log
        WHERE success = 1
        GROUP BY url
        ORDER BY hits DESC
        LIMIT 20
    """)
    top_recipes = [dict(row) for row in cur.fetchall()]

    return {
        "overview": overview,
        "daily": daily,
        "top_recipes": top_recipes,
    }
