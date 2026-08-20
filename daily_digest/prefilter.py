"""Heuristic prefilter: kill marketing/changelog noise before spending LLM tokens.

The probe of these feeds showed roughly 4 in 5 posts are product launches,
release notes, or company news. This stage removes them for free.
"""

from __future__ import annotations

import re

from .config import COMPETENCIES

MIN_WORDS = 600

# Raised from 3.0 after observing a 78% pass rate on the first live run; with
# full body text now available the score distribution shifted upward.
PASS_THRESHOLD = 6.0

# Titles matching these are almost never system-design content.
KILL_PATTERNS = [
    r"\bpatch notes\b",
    r"\bchangelog\b",
    r"\brelease notes\b",
    r"\bwhat'?s new\b",
    r"\bnow (?:generally )?available\b",
    r"\bgenerally available\b",
    r"\bnow in (?:public |private )?(?:beta|preview|ga)\b",
    r"\bwe'?re hiring\b",
    r"\bjoin (?:our|the) team\b",
    r"\bpartners? with\b",
    r"\bannouncing (?:our )?(?:partnership|series [a-z]|funding)\b",
    r"\braises \$",
    r"\bwelcome to the team\b",
    r"\blife at\b",
    r"\bintern(?:ship)? (?:program|experience)\b",
    r"\bemployee spotlight\b",
    r"\bwebinar\b",
    r"\bregister now\b",
    r"\bevent recap\b",
    r"\bsummit\b",
    r"\bnamed a leader\b",
    r"\bmagic quadrant\b",
    r"\bcustomer story\b",
    r"\bweek in review\b",
    r"\broundup\b",
    r"\bpricing update\b",
    r"\bfedramp\b",
]

# Signals of a genuine engineering deep-dive.
DEPTH_PATTERNS = [
    (r"\bhow we (?:built|scaled|migrated|rebuilt|redesigned|fixed)\b", 3.0),
    (r"\b(?:building|scaling|designing|rearchitect\w*)\b", 2.0),
    (r"\barchitectur\w+\b", 2.0),
    (r"\bunder the hood\b", 2.5),
    (r"\bdeep dive\b", 2.5),
    (r"\blessons learned\b", 2.0),
    (r"\bpost-?mortem\b", 3.0),
    (r"\boutage\b", 2.5),
    (r"\bincident\b", 2.0),
    (r"\bat scale\b", 2.5),
    (r"\b(?:billions?|millions?|trillions?) of\b", 2.0),
    (r"\bp9[59]\b|\btail latency\b", 2.5),
    (r"\bthroughput\b|\blatency\b", 1.5),
    (r"\bmigrat\w+\b", 1.5),
    (r"\btrade-?offs?\b", 2.0),
    (r"\bwhy we\b", 1.5),
    (r"\bbenchmark\w*\b", 1.5),
    (r"\bdistributed\b|\bconsensus\b|\breplication\b|\bshard\w*\b", 2.0),
    (r"\bbottleneck\b|\boptimiz\w+\b", 1.5),
    (r"\bfailure modes?\b", 2.0),
]

_KILL_RE = [re.compile(p, re.I) for p in KILL_PATTERNS]
_DEPTH_RE = [(re.compile(p, re.I), w) for p, w in DEPTH_PATTERNS]

# Launch/marketing language. Not an outright kill (a launch post can still carry
# real architecture detail) but a strong negative signal, which matters most in
# heuristic-only mode where there is no LLM to catch the nuance.
SOFT_PENALTIES = [
    (r"^\s*introducing\b", 5.0),
    (r"^\s*announcing\b", 5.0),
    (r"\bintroduc(?:ing|es)\b", 3.0),
    (r"\bannounc(?:ing|es)\b", 3.0),
    (r"\bwe'?re (?:excited|thrilled|happy) to\b", 4.0),
    (r"\bnow supports?\b", 3.0),
    (r"\bcomes to\b", 2.0),
    (r"\bnew in\b", 2.0),
    (r"\bget started with\b", 3.0),
    (r"\bhow to use\b", 2.0),
]
_SOFT_RE = [(re.compile(p, re.I), w) for p, w in SOFT_PENALTIES]


def classify_competency(text: str) -> tuple[str | None, int]:
    """Return the best-matching competency and its keyword hit count."""
    lowered = text.lower()
    best, best_hits = None, 0
    for name, keywords in COMPETENCIES.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best, best_hits = name, hits
    return best, best_hits


def evaluate(title: str, summary: str, body: str, word_count: int) -> dict:
    """Score an article. Returns pass/fail, score, reason, and competency."""
    haystack_title = title or ""
    haystack_full = f"{title}\n{summary}\n{body or ''}"

    for pattern in _KILL_RE:
        if pattern.search(haystack_title):
            return {
                "passed": False,
                "score": 0.0,
                "reason": f"title matched noise pattern /{pattern.pattern}/",
                "competency": None,
            }

    if word_count <= 0:
        return {
            "passed": False,
            "score": 0.0,
            "reason": "no body text could be extracted",
            "competency": None,
        }

    if word_count < MIN_WORDS:
        return {
            "passed": False,
            "score": 0.0,
            "reason": f"too short ({word_count} words < {MIN_WORDS})",
            "competency": None,
        }

    score = 0.0
    for pattern, weight in _DEPTH_RE:
        if pattern.search(haystack_title):
            score += weight * 1.5  # title signals are stronger than body signals
        elif pattern.search(haystack_full):
            score += weight * 0.5

    competency, hits = classify_competency(haystack_full)
    score += min(hits, 8) * 0.6

    for pattern, penalty in _SOFT_RE:
        if pattern.search(haystack_title):
            score -= penalty

    # Long-form is a decent proxy for depth, with diminishing returns.
    if word_count >= 1200:
        score += 1.5
    if word_count >= 2500:
        score += 1.5

    score = max(0.0, score)
    passed = score >= PASS_THRESHOLD and competency is not None
    return {
        "passed": passed,
        "score": round(score, 2),
        "reason": "" if passed else f"weak signal (score {score:.1f})",
        "competency": competency,
    }
