"""Full-text extraction. Titles lie; depth judgements need the body."""

from __future__ import annotations

import httpx
import trafilatura

from . import db
from .config import USER_AGENT


def extract_one(client: httpx.Client, url: str) -> tuple[str, int]:
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001 - unreachable article is not fatal
        return "", 0
    text = trafilatura.extract(
        resp.text, include_comments=False, include_tables=False, favor_precision=True
    )
    if not text:
        return "", 0
    return text, len(text.split())


def enrich_missing(limit: int = 60, verbose: bool = True) -> int:
    """Download body text for articles that don't have it yet."""
    headers = {"User-Agent": USER_AGENT}
    done = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, url FROM articles WHERE body IS NULL ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return 0
        with httpx.Client(timeout=25, headers=headers, follow_redirects=True) as client:
            for row in rows:
                text, words = extract_one(client, row["url"])
                conn.execute(
                    "UPDATE articles SET body = ?, word_count = ? WHERE id = ?",
                    (text, words, row["id"]),
                )
                done += 1
        if verbose:
            print(f"  extracted body text for {done} articles")
    return done
