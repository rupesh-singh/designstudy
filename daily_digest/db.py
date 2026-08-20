"""SQLite persistence layer."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    source_key      TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    body            TEXT,
    word_count      INTEGER DEFAULT 0,
    published_at    TEXT,
    fetched_at      TEXT NOT NULL,
    prefilter_score REAL,
    prefilter_pass  INTEGER DEFAULT 0,
    reject_reason   TEXT,
    competency      TEXT,
    llm_score       REAL,
    llm_reason      TEXT,
    llm_questions   TEXT,
    final_score     REAL,
    served_on       TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_served ON articles(served_on);
CREATE INDEX IF NOT EXISTS idx_articles_pass ON articles(prefilter_pass, served_on);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at      TEXT NOT NULL,
    new_items   INTEGER DEFAULT 0,
    passed      INTEGER DEFAULT 0,
    scored      INTEGER DEFAULT 0,
    served      INTEGER DEFAULT 0,
    notes       TEXT
);
"""


def article_id(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()[:20]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_article(conn: sqlite3.Connection, item: dict) -> bool:
    """Insert if new. Returns True when a new row was created."""
    aid = article_id(item["url"])
    exists = conn.execute("SELECT 1 FROM articles WHERE id = ?", (aid,)).fetchone()
    if exists:
        return False
    conn.execute(
        """
        INSERT INTO articles (id, url, source_key, source_name, title, summary,
                              published_at, fetched_at, body, word_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid,
            item["url"],
            item["source_key"],
            item["source_name"],
            item["title"],
            item.get("summary", ""),
            item.get("published_at"),
            utcnow(),
            item.get("body") or None,
            item.get("word_count") or 0,
        ),
    )
    return True


def competency_coverage(conn: sqlite3.Connection) -> dict[str, int]:
    """How many articles of each competency have already been served."""
    rows = conn.execute(
        "SELECT competency, COUNT(*) c FROM articles "
        "WHERE served_on IS NOT NULL AND competency IS NOT NULL GROUP BY competency"
    ).fetchall()
    return {r["competency"]: r["c"] for r in rows}


def recently_served_sources(conn: sqlite3.Connection, limit: int = 6) -> list[str]:
    rows = conn.execute(
        "SELECT source_key FROM articles WHERE served_on IS NOT NULL "
        "ORDER BY served_on DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r["source_key"] for r in rows]
