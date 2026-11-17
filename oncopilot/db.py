"""SQLite 本地存储层：试验快照、同步批次、画像与匹配结果。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS studies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    registry_id TEXT NOT NULL,
    title TEXT,
    condition TEXT,
    biomarker TEXT,
    phase TEXT,
    status TEXT,
    status_date TEXT,
    last_update_submitted TEXT,
    country TEXT,
    location_text TEXT,
    eligibility TEXT,
    intervention TEXT,
    sponsor TEXT,
    gender TEXT,
    min_age TEXT,
    max_age TEXT,
    url TEXT,
    raw_json TEXT,
    fetched_at TEXT,
    UNIQUE(source, registry_id)
);

CREATE INDEX IF NOT EXISTS idx_studies_condition ON studies(condition);
CREATE INDEX IF NOT EXISTS idx_studies_biomarker ON studies(biomarker);
CREATE INDEX IF NOT EXISTS idx_studies_status ON studies(status);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    records_total INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    data_timestamp TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS match_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@contextmanager
def get_conn(db_path: Path | str | None = None):
    path = str(db_path or config.DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_study(conn: sqlite3.Connection, record: dict) -> bool:
    """写入或更新一条试验记录，返回是否为新记录。"""
    existing = conn.execute(
        "SELECT id FROM studies WHERE source = ? AND registry_id = ?",
        (record["source"], record["registry_id"]),
    ).fetchone()
    fetched_at = now_iso()
    if existing:
        conn.execute(
            """
            UPDATE studies SET title=?, condition=?, biomarker=?, phase=?, status=?,
                status_date=?, last_update_submitted=?, country=?, location_text=?,
                eligibility=?, intervention=?, sponsor=?, gender=?, min_age=?, max_age=?,
                url=?, raw_json=?, fetched_at=?
            WHERE source=? AND registry_id=?
            """,
            (
                record.get("title"), record.get("condition"), record.get("biomarker"),
                record.get("phase"), record.get("status"), record.get("status_date"),
                record.get("last_update_submitted"), record.get("country"),
                record.get("location_text"), record.get("eligibility"),
                record.get("intervention"), record.get("sponsor"), record.get("gender"),
                record.get("min_age"), record.get("max_age"), record.get("url"),
                record.get("raw_json"), fetched_at,
                record["source"], record["registry_id"],
            ),
        )
        return False
    conn.execute(
        """
        INSERT INTO studies (source, registry_id, title, condition, biomarker, phase, status,
            status_date, last_update_submitted, country, location_text, eligibility,
            intervention, sponsor, gender, min_age, max_age, url, raw_json, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record["source"], record["registry_id"], record.get("title"),
            record.get("condition"), record.get("biomarker"), record.get("phase"),
            record.get("status"), record.get("status_date"),
            record.get("last_update_submitted"), record.get("country"),
            record.get("location_text"), record.get("eligibility"),
            record.get("intervention"), record.get("sponsor"), record.get("gender"),
            record.get("min_age"), record.get("max_age"), record.get("url"),
            record.get("raw_json"), fetched_at,
        ),
    )
    return True


def latest_sync(conn: sqlite3.Connection, source: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM sync_log WHERE source=? ORDER BY id DESC LIMIT 1", (source,)
    ).fetchone()
    return dict(row) if row else None
