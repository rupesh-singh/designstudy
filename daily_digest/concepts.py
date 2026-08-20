"""Concept cards: parse the markdown reference into drillable, scheduled cards.

A reference you re-read is recognition practice; a reference that asks you
questions on a schedule is recall practice. This module turns concepts/*.md into
SQLite rows with SM-2-style spaced repetition state.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import markdown

from . import db
from .config import ROOT

CONCEPTS_DIR = ROOT / "concepts"
AGENTIC_DIR = ROOT / "agentic-ai"

SCHEMA = """
CREATE TABLE IF NOT EXISTS concepts (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    source_file    TEXT NOT NULL,
    file_title     TEXT,
    section        TEXT,
    body           TEXT NOT NULL,
    competency     TEXT,
    track          TEXT,
    ease           REAL DEFAULT 2.5,
    interval_days  INTEGER DEFAULT 0,
    reps           INTEGER DEFAULT 0,
    lapses         INTEGER DEFAULT 0,
    due_on         TEXT,
    last_grade     INTEGER,
    last_reviewed  TEXT
);
CREATE INDEX IF NOT EXISTS idx_concepts_due ON concepts(due_on);

CREATE TABLE IF NOT EXISTS concept_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id  TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    grade       INTEGER NOT NULL,
    interval_after INTEGER
);
"""

# Which competency each reference file feeds. A file only becomes drillable if it
# appears here, which keeps index and template files out of the card set.
FILE_COMPETENCY = {
    "01": "scale-and-performance",
    "02": "storage-and-data",
    "03": "storage-and-data",
    "04": "distributed-systems",
    "05": "scale-and-performance",
    "06": "storage-and-data",
    "07": "distributed-systems",
    "08": "distributed-systems",
    "09": "queues-and-streaming",
    "10": "caching",
    "11": "architecture-and-apis",
    "12": "reliability-and-incidents",
    "13": "migrations",
    "14": "observability",
    "15": "security-and-multitenancy",
    "16": "scale-and-performance",
    "17": "architecture-and-apis",
}

AGENTIC_COMPETENCY = {
    "a01": "llm-foundations",
    "a02": "context-engineering",
    "a03": "retrieval-and-rag",
    "a04": "agent-architecture",
    "a05": "tools-and-integration",
    "a06": "memory-and-state",
    "a07": "evaluation",
    "a08": "production-reliability",
    "a09": "safety-and-security",
    "a10": "model-adaptation",
    "a11": "inference-infra",
    "a12": "multi-agent",
    "a13": "agent-architecture",
}

# Tracks are drilled independently; card ids stay globally unique because the
# agentic files use an 'a' prefix.
TRACKS: dict[str, dict] = {
    "system-design": {"dir": CONCEPTS_DIR, "competencies": FILE_COMPETENCY},
    "agentic-ai": {"dir": AGENTIC_DIR, "competencies": AGENTIC_COMPETENCY},
}

FILE_PREFIX_RE = re.compile(r"^([a-z]?\d\d)-")

GRADE_LABELS = {0: "again", 1: "hard", 2: "good", 3: "easy"}


LABEL_RE = re.compile(
    r"^\*\*(What|Use when|Use it when|Advantages|Tradeoffs|Trade-offs|Staff signal)\.?\*\*",
    re.I,
)


def normalize_markdown(body: str) -> str:
    """Insert the blank lines Python-Markdown needs to see structure.

    Cards are authored compactly (label lines and bullets with no blank lines
    between them). Without separation, Markdown folds the whole card into one
    paragraph and never renders the bullet lists.
    """
    lines = body.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        starts_block = bool(LABEL_RE.match(stripped)) or stripped.startswith(("- ", "* "))
        previous_is_list = out and out[-1].strip().startswith(("- ", "* "))
        # A bullet directly after another bullet is already a valid list.
        if starts_block and out and out[-1].strip() and not (
            previous_is_list and stripped.startswith(("- ", "* "))
        ):
            out.append("")
        out.append(line)
    return "\n".join(out)


def card_to_html(body: str) -> str:
    return markdown.markdown(normalize_markdown(body), extensions=["tables", "sane_lists"])


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Databases created before the agentic track lack the column, so add and
    # backfill it before anything indexes or queries it.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(concepts)")}
    if "track" not in columns:
        conn.execute("ALTER TABLE concepts ADD COLUMN track TEXT")
    conn.execute(
        "UPDATE concepts SET track = CASE WHEN source_file LIKE 'a%' "
        "THEN 'agentic-ai' ELSE 'system-design' END WHERE track IS NULL"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_concepts_track ON concepts(track)")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]


def parse_file(path: Path, track: str, competencies: dict[str, str]) -> list[dict]:
    """Extract '### Concept' cards, tagged with their '## Section' heading."""
    text = path.read_text(encoding="utf-8")
    match = FILE_PREFIX_RE.match(path.name)
    prefix = match.group(1) if match else path.name[:2]
    competency = competencies.get(prefix)

    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    file_title = title_match.group(1).strip() if title_match else path.stem

    cards: list[dict] = []
    section = ""
    # Split on headings while keeping track of level.
    parts = re.split(r"^(##+)\s+(.+)$", text, flags=re.M)
    # parts = [pre, hashes, heading, body, hashes, heading, body, ...]
    for i in range(1, len(parts) - 2, 3):
        hashes, heading, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        if len(hashes) == 2:
            section = heading
            continue
        if len(hashes) != 3:
            continue
        if not body.strip():
            continue
        cards.append(
            {
                "id": f"{prefix}-{slugify(heading)}",
                "name": heading,
                "source_file": path.name,
                "file_title": file_title,
                "section": section,
                "body": body.strip(),
                "competency": competency,
                "track": track,
            }
        )
    return cards


def _track_files(track: str) -> list[Path]:
    spec = TRACKS[track]
    directory: Path = spec["dir"]
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.glob("*.md")):
        match = FILE_PREFIX_RE.match(path.name)
        # Only numbered files with a competency mapping are drillable; this
        # excludes index and template files.
        if match and match.group(1) in spec["competencies"]:
            result.append(path)
    return result


def sync(verbose: bool = True) -> tuple[int, int]:
    """Load concept cards into the database, preserving review scheduling."""
    added = updated = 0
    all_files: list[str] = []
    with db.connect() as conn:
        init(conn)
        for track, spec in TRACKS.items():
            files = _track_files(track)
            all_files.extend(p.name for p in files)
            for path in files:
                for card in parse_file(path, track, spec["competencies"]):
                    existing = conn.execute(
                        "SELECT id FROM concepts WHERE id = ?", (card["id"],)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            """UPDATE concepts SET name=?, source_file=?, file_title=?,
                               section=?, body=?, competency=?, track=? WHERE id=?""",
                            (
                                card["name"],
                                card["source_file"],
                                card["file_title"],
                                card["section"],
                                card["body"],
                                card["competency"],
                                card["track"],
                                card["id"],
                            ),
                        )
                        updated += 1
                    else:
                        conn.execute(
                            """INSERT INTO concepts (id, name, source_file, file_title,
                               section, body, competency, track, due_on)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (
                                card["id"],
                                card["name"],
                                card["source_file"],
                                card["file_title"],
                                card["section"],
                                card["body"],
                                card["competency"],
                                card["track"],
                                date.today().isoformat(),
                            ),
                        )
                        added += 1
        # Drop cards whose source file was renamed or removed.
        placeholders = ",".join("?" for _ in all_files) or "''"
        conn.execute(
            f"DELETE FROM concepts WHERE source_file NOT IN ({placeholders})", all_files
        )
    if verbose:
        print(f"  concepts synced: {added} new, {updated} updated, {len(all_files)} files")
    return added, updated


def _next_interval(row: sqlite3.Row, grade: int) -> tuple[int, float, int, int]:
    """SM-2 style scheduling. Returns (interval_days, ease, reps, lapses)."""
    ease = row["ease"] or 2.5
    interval = row["interval_days"] or 0
    reps = row["reps"] or 0
    lapses = row["lapses"] or 0

    if grade == 0:
        # Failed recall: reset the ladder, review again immediately.
        return 0, max(1.3, ease - 0.20), 0, lapses + 1
    if grade == 1:
        ease = max(1.3, ease - 0.15)
        interval = max(1, int(round(max(1, interval) * 1.2)))
    elif grade == 2:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = int(round(max(1, interval) * ease))
    else:
        ease = min(3.0, ease + 0.15)
        interval = int(round(max(1, interval) * ease * 1.3)) if reps else 4

    return max(1, interval), ease, reps + 1, lapses


def grade(concept_id: str, grade_value: int) -> dict | None:
    """Record a review outcome and reschedule the card."""
    if grade_value not in GRADE_LABELS:
        raise ValueError(f"grade must be one of {sorted(GRADE_LABELS)}")
    with db.connect() as conn:
        init(conn)
        row = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if row is None:
            return None
        interval, ease, reps, lapses = _next_interval(row, grade_value)
        due = date.today() + timedelta(days=interval)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """UPDATE concepts SET ease=?, interval_days=?, reps=?, lapses=?,
               due_on=?, last_grade=?, last_reviewed=? WHERE id=?""",
            (ease, interval, reps, lapses, due.isoformat(), grade_value, now, concept_id),
        )
        conn.execute(
            "INSERT INTO concept_reviews (concept_id, reviewed_at, grade, interval_after)"
            " VALUES (?,?,?,?)",
            (concept_id, now, grade_value, interval),
        )
        return {
            "id": concept_id,
            "name": row["name"],
            "grade": GRADE_LABELS[grade_value],
            "interval_days": interval,
            "due_on": due.isoformat(),
        }


def due_cards(limit: int = 5, competency: str | None = None,
              track: str | None = None) -> list[sqlite3.Row]:
    """Cards scheduled for review today, weakest first."""
    today = date.today().isoformat()
    clauses = ["(due_on IS NULL OR due_on <= ?)"]
    params: list = [today]
    if competency:
        clauses.append("competency = ?")
        params.append(competency)
    if track:
        clauses.append("track = ?")
        params.append(track)
    query = (
        "SELECT * FROM concepts WHERE " + " AND ".join(clauses)
        # Never-seen and previously-failed cards come first.
        + " ORDER BY (reps = 0) DESC, lapses DESC, due_on ASC, RANDOM() LIMIT ?"
    )
    params.append(limit)
    with db.connect() as conn:
        init(conn)
        return conn.execute(query, params).fetchall()


def stats(track: str | None = None) -> dict:
    where = " WHERE track = ?" if track else ""
    args: tuple = (track,) if track else ()
    with db.connect() as conn:
        init(conn)
        total = conn.execute(f"SELECT COUNT(*) c FROM concepts{where}", args).fetchone()["c"]
        if not total:
            return {"total": 0}
        today = date.today().isoformat()
        due = conn.execute(
            f"SELECT COUNT(*) c FROM concepts WHERE (due_on IS NULL OR due_on <= ?)"
            + (" AND track = ?" if track else ""),
            (today, *args),
        ).fetchone()["c"]
        new = conn.execute(
            f"SELECT COUNT(*) c FROM concepts WHERE reps = 0"
            + (" AND track = ?" if track else ""),
            args,
        ).fetchone()["c"]
        learned = conn.execute(
            f"SELECT COUNT(*) c FROM concepts WHERE reps > 0 AND interval_days >= 21"
            + (" AND track = ?" if track else ""),
            args,
        ).fetchone()["c"]
        reviews = conn.execute("SELECT COUNT(*) c FROM concept_reviews").fetchone()["c"]
        by_file = conn.execute(
            f"SELECT track, source_file, COUNT(*) n,"
            f" SUM(CASE WHEN reps>0 THEN 1 ELSE 0 END) seen"
            f" FROM concepts{where} GROUP BY track, source_file ORDER BY track, source_file",
            args,
        ).fetchall()
        by_track = conn.execute(
            "SELECT track, COUNT(*) n, SUM(CASE WHEN reps>0 THEN 1 ELSE 0 END) seen"
            " FROM concepts GROUP BY track ORDER BY track"
        ).fetchall()
        return {
            "total": total,
            "due": due,
            "new": new,
            "learned": learned,
            "reviews": reviews,
            "by_file": by_file,
            "by_track": by_track,
        }
