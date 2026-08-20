"""Fetch RSS/Atom feeds and store new items."""

from __future__ import annotations

import time
from calendar import timegm
from datetime import datetime, timezone

import feedparser
import httpx

from . import db
from .config import SOURCES, USER_AGENT, Source


def _published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).isoformat(
                    timespec="seconds"
                )
            except (ValueError, OverflowError):
                continue
    return None


def _clean(text: str, limit: int = 1200) -> str:
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _feed_body(entry) -> tuple[str, int]:
    """Many feeds (notably Medium-hosted ones) ship the full post inline.

    Using it avoids a fetch and works where scraping is blocked.
    """
    candidates = []
    for item in entry.get("content") or []:
        value = item.get("value") if isinstance(item, dict) else None
        if value:
            candidates.append(value)
    if not candidates and entry.get("summary"):
        candidates.append(entry["summary"])
    if not candidates:
        return "", 0
    best = max(candidates, key=len)
    text = _clean(best, limit=200_000)
    words = len(text.split())
    # Short values are teaser blurbs, not the article body.
    return (text, words) if words >= 200 else ("", 0)


def fetch_source(client: httpx.Client, source: Source) -> list[dict]:
    resp = client.get(source.feed_url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries:
        url = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not url or not title:
            continue
        body, words = _feed_body(entry)
        items.append(
            {
                "url": url,
                "title": title,
                "summary": _clean(entry.get("summary", "")),
                "published_at": _published(entry),
                "source_key": source.key,
                "source_name": source.name,
                "body": body,
                "word_count": words,
            }
        )
    return items


def collect(limit_per_source: int = 25, verbose: bool = True) -> int:
    """Pull all feeds, store new items. Returns count of new articles."""
    new_total = 0
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, */*"}
    with httpx.Client(timeout=25, headers=headers, follow_redirects=True) as client:
        with db.connect() as conn:
            for source in SOURCES:
                try:
                    items = fetch_source(client, source)[:limit_per_source]
                except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
                    if verbose:
                        print(f"  [warn] {source.name}: {type(exc).__name__}: {exc}")
                    continue
                added = sum(1 for item in items if db.upsert_article(conn, item))
                new_total += added
                if verbose:
                    print(f"  {source.name:<18} {len(items):>3} seen, {added:>3} new")
                time.sleep(0.4)
    return new_total
