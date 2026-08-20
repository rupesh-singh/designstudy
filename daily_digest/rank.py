"""Ranking and daily selection.

Two stages:
  1. score()  - rate prefiltered candidates (LLM if configured, else heuristic)
  2. select() - pick the day's slate using competency-gap + source-diversity
                constraints rather than naive top-N, and blend fresh + backlog.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

from . import db
from .config import (
    ARTICLES_PER_DAY,
    BACKLOG_SLOTS,
    COMPETENCIES,
    FRESH_WINDOW_DAYS,
    SOURCES,
    LLMConfig,
)

SOURCE_WEIGHTS = {s.key: s.weight for s in SOURCES}

SYSTEM_PROMPT = """You evaluate engineering blog posts for a senior engineer \
preparing for Staff Software Engineer system-design interviews.

Score 0-10 on how much the post teaches about designing real systems:
  9-10 = deep architecture/scaling/incident analysis with concrete tradeoffs and numbers
  6-8  = solid engineering deep-dive with real technical substance
  3-5  = shallow technical overview, tutorial, or thin case study
  0-2  = product launch, marketing, release notes, company news, hiring

Reward: failure modes, tradeoffs considered and rejected, migration strategy,
concrete metrics, capacity/scale numbers, "why" over "what".
Penalize: vendor pitch, feature announcement, no technical depth.

Return STRICT JSON only:
{"score": <0-10 number>,
 "competency": "<one of: %s>",
 "reason": "<max 20 words>",
 "questions": ["<3 retrieval-practice questions testing design understanding>"]}""" % (
    ", ".join(COMPETENCIES)
)


def _llm_score(cfg: LLMConfig, title: str, source: str, body: str) -> dict | None:
    excerpt = (body or "")[:6000]
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Source: {source}\nTitle: {title}\n\nArticle:\n{excerpt}",
            },
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = httpx.post(
            f"{cfg.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return {
            "score": float(data.get("score", 0)),
            "competency": data.get("competency"),
            "reason": (data.get("reason") or "")[:200],
            "questions": data.get("questions") or [],
        }
    except Exception as exc:  # noqa: BLE001 - fall back to heuristic scoring
        print(f"  [warn] LLM scoring failed ({type(exc).__name__}: {exc}); using heuristic")
        return None


def _heuristic_questions(title: str, competency: str | None) -> list[str]:
    topic = (competency or "this system").replace("-", " ")
    return [
        f"What core problem forced the team to change their approach in \u201c{title}\u201d?",
        f"Which alternative designs would you weigh for this {topic} problem, and why reject them?",
        "What breaks first if traffic grows 10x, and what would you measure to prove it?",
    ]


def score(limit: int = 40, verbose: bool = True) -> int:
    """Score prefiltered candidates that have not been scored yet."""
    cfg = LLMConfig()
    if verbose:
        mode = f"LLM ({cfg.model})" if cfg.enabled else "heuristic only (no API key set)"
        print(f"  scoring mode: {mode}")

    scored = 0
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, title, source_name, body, prefilter_score, competency
            FROM articles
            WHERE prefilter_pass = 1 AND final_score IS NULL AND served_on IS NULL
            ORDER BY prefilter_score DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        for row in rows:
            result = _llm_score(cfg, row["title"], row["source_name"], row["body"]) if cfg.enabled else None
            if result:
                llm_score = result["score"]
                competency = result["competency"] or row["competency"]
                reason = result["reason"]
                questions = result["questions"]
            else:
                # Map the unbounded heuristic score onto 0-10 asymptotically so
                # ordering is preserved instead of saturating at the cap.
                raw = row["prefilter_score"] or 0.0
                llm_score = round(10.0 * (1.0 - math.exp(-raw / 9.0)), 2)
                competency = row["competency"]
                reason = "heuristic score (no LLM configured)"
                questions = _heuristic_questions(row["title"], competency)

            conn.execute(
                """
                UPDATE articles
                SET llm_score = ?, competency = ?, llm_reason = ?,
                    llm_questions = ?, final_score = ?
                WHERE id = ?
                """,
                (llm_score, competency, reason, json.dumps(questions), llm_score, row["id"]),
            )
            scored += 1
    if verbose:
        print(f"  scored {scored} candidates")
    return scored


def _is_fresh(published_at: str | None) -> bool:
    if not published_at:
        return False
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= datetime.now(timezone.utc) - timedelta(days=FRESH_WINDOW_DAYS)


def _adjusted(row: sqlite3.Row, coverage: dict[str, int], recent_sources: list[str]) -> float:
    """Apply competency-gap and source-diversity adjustments to the raw score."""
    value = row["final_score"] or 0.0

    # Reward under-covered competencies so breadth accumulates over time.
    seen = coverage.get(row["competency"], 0)
    value += max(0.0, 3.0 - seen * 0.5)

    # Penalize sources served in the last few days.
    if row["source_key"] in recent_sources:
        value -= 1.5 * (recent_sources.count(row["source_key"]))

    value *= SOURCE_WEIGHTS.get(row["source_key"], 1.0)
    return value


def select(count: int = ARTICLES_PER_DAY, verbose: bool = True) -> list[sqlite3.Row]:
    """Pick today's slate: fresh items first, backlog fills remaining slots."""
    today = datetime.now(timezone.utc).date().isoformat()
    with db.connect() as conn:
        already = conn.execute(
            "SELECT * FROM articles WHERE served_on = ? ORDER BY final_score DESC", (today,)
        ).fetchall()
        if already:
            if verbose:
                print(f"  already selected {len(already)} articles for {today}")
            return already

        candidates = conn.execute(
            """
            SELECT * FROM articles
            WHERE final_score IS NOT NULL AND served_on IS NULL
            ORDER BY final_score DESC LIMIT 200
            """
        ).fetchall()
        if not candidates:
            return []

        coverage = db.competency_coverage(conn)
        recent_sources = db.recently_served_sources(conn)

        fresh = [r for r in candidates if _is_fresh(r["published_at"])]
        backlog = [r for r in candidates if not _is_fresh(r["published_at"])]

        fresh_slots = max(0, count - BACKLOG_SLOTS)
        chosen: list[sqlite3.Row] = []
        used_sources: list[str] = list(recent_sources)
        used_competencies: set[str] = set()

        def take(pool: list[sqlite3.Row], slots: int, enforce_variety: bool = True) -> None:
            if slots <= 0:
                return
            ranked = sorted(pool, key=lambda r: _adjusted(r, coverage, used_sources), reverse=True)
            chosen_ids = {c["id"] for c in chosen}
            for row in ranked:
                if slots <= 0:
                    return
                if row["id"] in chosen_ids:
                    continue
                # Avoid two articles on the same competency in one day.
                if enforce_variety and row["competency"] and row["competency"] in used_competencies:
                    continue
                chosen.append(row)
                chosen_ids.add(row["id"])
                used_sources.insert(0, row["source_key"])
                if row["competency"]:
                    used_competencies.add(row["competency"])
                slots -= 1

        take(fresh, fresh_slots)
        take(backlog, count - len(chosen))
        # If diversity constraints starved us, top up from anything remaining.
        if len(chosen) < count:
            take(candidates, count - len(chosen), enforce_variety=False)

        for row in chosen:
            conn.execute("UPDATE articles SET served_on = ? WHERE id = ?", (today, row["id"]))

        ids = [r["id"] for r in chosen]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return conn.execute(
            f"SELECT * FROM articles WHERE id IN ({placeholders})", ids
        ).fetchall()
