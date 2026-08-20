"""Command-line entrypoint for the daily digest pipeline."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

from . import collect, concepts, db, digest, extract, prefilter, rank
from .config import ARTICLES_PER_DAY, NEEDS_ADAPTER, ROOT, SOURCES


def _apply_prefilter(verbose: bool = True) -> int:
    """Run heuristic screening on any article that hasn't been screened yet."""
    passed = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, summary, body, word_count FROM articles "
            "WHERE prefilter_score IS NULL AND body IS NOT NULL"
        ).fetchall()
        for row in rows:
            result = prefilter.evaluate(
                row["title"], row["summary"] or "", row["body"] or "", row["word_count"] or 0
            )
            conn.execute(
                """UPDATE articles SET prefilter_score = ?, prefilter_pass = ?,
                   reject_reason = ?, competency = ? WHERE id = ?""",
                (
                    result["score"],
                    1 if result["passed"] else 0,
                    result["reason"],
                    result["competency"],
                    row["id"],
                ),
            )
            passed += 1 if result["passed"] else 0
        if verbose:
            print(f"  prefiltered {len(rows)} articles, {passed} passed")
    return passed


def cmd_run(args: argparse.Namespace) -> int:
    db.init()
    print("[1/5] Collecting feeds...")
    new_items = collect.collect(verbose=not args.quiet)
    print(f"      {new_items} new articles")

    print("[2/5] Extracting article text...")
    extract.enrich_missing(limit=args.extract_limit, verbose=not args.quiet)

    print("[3/5] Prefiltering...")
    _apply_prefilter(verbose=not args.quiet)

    print("[4/5] Scoring candidates...")
    rank.score(limit=args.score_limit, verbose=not args.quiet)

    print("[5/5] Selecting today's slate...")
    chosen = rank.select(count=args.count, verbose=not args.quiet)
    cards = []
    if not args.no_revision:
        try:
            cards = concepts.due_cards(limit=args.revise_count, track=args.revise_track)
        except sqlite3.Error:
            cards = []
    path = digest.render(chosen, cards=cards, verbose=not args.quiet)

    print()
    if chosen:
        for i, row in enumerate(chosen, 1):
            print(f"  {i}. [{row['source_name']}] {row['title']}")
            print(f"     {row['competency']} | score {row['final_score']:.1f} | {row['url']}")
    else:
        print("  No articles met the bar today.")
    print(f"\nDigest: {path}")
    if cards:
        print(f"Revision: {len(cards)} concept card(s) included")

    if args.open:
        webbrowser.open(Path(path).resolve().as_uri())
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    db.init()
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
        passed = conn.execute("SELECT COUNT(*) c FROM articles WHERE prefilter_pass=1").fetchone()["c"]
        served = conn.execute("SELECT COUNT(*) c FROM articles WHERE served_on IS NOT NULL").fetchone()["c"]
        print(f"articles stored : {total}")
        print(f"passed filter   : {passed}  ({passed/total*100:.0f}%)" if total else "")
        print(f"served to you   : {served}")
        print("\nby source:")
        for row in conn.execute(
            "SELECT source_name, COUNT(*) c, SUM(prefilter_pass) p FROM articles "
            "GROUP BY source_name ORDER BY c DESC"
        ):
            print(f"  {row['source_name']:<18} {row['c']:>4} stored  {row['p'] or 0:>3} passed")
        print("\ncompetency coverage:")
        for name, count in sorted(db.competency_coverage(conn).items(), key=lambda kv: -kv[1]):
            print(f"  {name:<28} {count}")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Deepen the candidate pool by extracting/scoring more historical items."""
    db.init()
    extract.enrich_missing(limit=args.limit, verbose=True)
    _apply_prefilter(verbose=True)
    rank.score(limit=args.limit, verbose=True)
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Clear scoring state (keeping fetched bodies) so filters can be retuned."""
    db.init()
    with db.connect() as conn:
        conn.execute(
            "UPDATE articles SET prefilter_score = NULL, prefilter_pass = 0, "
            "reject_reason = NULL, competency = NULL, llm_score = NULL, "
            "llm_reason = NULL, llm_questions = NULL, final_score = NULL"
            + ("" if args.keep_history else ", served_on = NULL")
        )
    print("scoring state cleared" + ("" if args.keep_history else " (including served history)"))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    """Report per-source health so silent breakage surfaces on its own."""
    db.init()
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT source_name,
                   COUNT(*) n,
                   SUM(CASE WHEN word_count > 0 THEN 1 ELSE 0 END) body_ok,
                   SUM(prefilter_pass) passed
            FROM articles GROUP BY source_name ORDER BY source_name
            """
        ).fetchall()

    seen = {r["source_name"] for r in rows}
    print(f"{'SOURCE':<18}{'ITEMS':>6}{'BODY':>6}{'PASS':>6}   STATUS")
    problems: list[str] = []
    for source in SOURCES:
        row = next((r for r in rows if r["source_name"] == source.name), None)
        if row is None or row["n"] == 0:
            status = "NO ITEMS - feed may be dead"
            problems.append(source.name)
            print(f"{source.name:<18}{0:>6}{0:>6}{0:>6}   {status}")
            continue
        n, body_ok, passed = row["n"], row["body_ok"] or 0, row["passed"] or 0
        if body_ok == 0:
            status = "BLOCKED - no body text extracted"
            problems.append(source.name)
        elif body_ok / n < 0.5:
            status = f"DEGRADED - only {body_ok}/{n} extracted"
            problems.append(source.name)
        elif passed == 0:
            status = "LOW VALUE - fetches fine, nothing passes filter"
        else:
            status = "ok"
        print(f"{source.name:<18}{n:>6}{body_ok:>6}{passed:>6}   {status}")

    stale = seen - {s.name for s in SOURCES}
    if stale:
        print(f"\nStored but no longer configured: {', '.join(sorted(stale))}")
        print("  run 'cli.py prune' to remove their rows")

    print(f"\nNot yet covered ({len(NEEDS_ADAPTER)} sources needing v1 adapters):")
    for name, reason in NEEDS_ADAPTER.items():
        print(f"  {name:<14} {reason}")

    if problems:
        print(f"\n{len(problems)} source(s) need attention: {', '.join(problems)}")
    return 1 if problems else 0


def cmd_prune(_: argparse.Namespace) -> int:
    """Delete rows from sources that are no longer configured."""
    db.init()
    keep = [s.name for s in SOURCES]
    placeholders = ",".join("?" for _ in keep)
    with db.connect() as conn:
        removed = conn.execute(
            f"DELETE FROM articles WHERE source_name NOT IN ({placeholders})", keep
        ).rowcount
    print(f"removed {removed} rows from deconfigured sources")
    return 0


def cmd_concepts(args: argparse.Namespace) -> int:
    """Load the markdown reference into drillable cards."""
    db.init()
    concepts.sync(verbose=not args.quiet)
    info = concepts.stats()
    if info.get("total") and not args.quiet:
        print(f"\n  {info['total']} cards | {info['due']} due | {info['new']} never seen")
        print("\n  by track:")
        for row in info["by_track"]:
            print(f"    {row['track']:<16} {row['n']:>4} cards  {row['seen']:>4} seen")
        print("\n  by file:")
        for row in info["by_file"]:
            print(f"    {row['source_file']:<46} {row['n']:>3} cards  {row['seen']:>3} seen")
    return 0


def _render_card(row, index: int, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"[{index}/{total}]  {row['name']}")
    print(f"        {row['file_title']} -> {row['section']}")
    print("=" * 78)


def cmd_revise(args: argparse.Namespace) -> int:
    """Spaced-repetition drill over the concept reference."""
    db.init()
    with db.connect() as conn:
        concepts.init(conn)
        has_cards = conn.execute("SELECT COUNT(*) c FROM concepts").fetchone()["c"]
    if not has_cards:
        print("No concept cards loaded yet. Run:  cli.py concepts")
        return 1

    cards = concepts.due_cards(
        limit=args.count, competency=args.competency, track=args.track
    )
    if not cards:
        info = concepts.stats(track=args.track)
        scope = f" in {args.track}" if args.track else ""
        print(f"Nothing due today{scope}. "
              f"{info.get('total', 0)} cards tracked, {info.get('learned', 0)} matured.")
        return 0

    if not args.interactive:
        print(f"{len(cards)} card(s) due. Recall each aloud before revealing.\n")
        for i, row in enumerate(cards, 1):
            status = "new" if row["reps"] == 0 else f"rep {row['reps']}, lapses {row['lapses']}"
            print(f"  {i}. {row['name']}")
            print(f"     {row['section']} | {status} | id: {row['id']}")
        print("\nReveal answers in the digest page, or run with --interactive to grade.")
        print("Grade manually with:  cli.py grade <id> <0=again 1=hard 2=good 3=easy>")
        return 0

    print(f"\n{len(cards)} card(s) due. Answer aloud, then press Enter to reveal.")
    for i, row in enumerate(cards, 1):
        _render_card(row, i, len(cards))
        try:
            input("\n  (recall it, then press Enter) ")
        except EOFError:
            print("\nNon-interactive stdin; use 'cli.py revise' without --interactive.")
            return 1
        print("\n" + row["body"])
        while True:
            try:
                answer = input("\n  grade [0=again 1=hard 2=good 3=easy, q=quit]: ").strip()
            except EOFError:
                return 1
            if answer.lower() in {"q", "quit"}:
                print("stopped.")
                return 0
            if answer in {"0", "1", "2", "3"}:
                result = concepts.grade(row["id"], int(answer))
                print(f"  -> {result['grade']}, next review in {result['interval_days']}d "
                      f"({result['due_on']})")
                break
            print("  enter 0, 1, 2, 3, or q")
    print("\nSession complete.")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    db.init()
    result = concepts.grade(args.concept_id, args.grade)
    if result is None:
        print(f"no such concept: {args.concept_id}")
        return 1
    print(f"{result['name']}: {result['grade']} -> next in {result['interval_days']}d "
          f"({result['due_on']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(prog="daily_digest", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="full pipeline: collect -> filter -> score -> digest")
    run.add_argument("--count", type=int, default=ARTICLES_PER_DAY)
    run.add_argument("--extract-limit", type=int, default=60)
    run.add_argument("--score-limit", type=int, default=40)
    run.add_argument("--open", action="store_true", help="open the digest in a browser")
    run.add_argument("--revise-count", type=int, default=5, help="concept cards to include")
    run.add_argument("--revise-track", choices=sorted(concepts.TRACKS),
                     help="limit revision cards to one track")
    run.add_argument("--no-revision", action="store_true", help="skip the revision section")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    stats = sub.add_parser("stats", help="show pipeline statistics")
    stats.set_defaults(func=cmd_stats)

    backfill = sub.add_parser("backfill", help="extract and score more of the stored backlog")
    backfill.add_argument("--limit", type=int, default=150)
    backfill.set_defaults(func=cmd_backfill)

    reset = sub.add_parser("reset", help="clear scores to retune filters without refetching")
    reset.add_argument("--keep-history", action="store_true", help="keep served_on history")
    reset.set_defaults(func=cmd_reset)

    doctor = sub.add_parser("doctor", help="per-source health check; exits 1 if any source is broken")
    doctor.set_defaults(func=cmd_doctor)

    prune = sub.add_parser("prune", help="delete rows from deconfigured sources")
    prune.set_defaults(func=cmd_prune)

    conc = sub.add_parser("concepts", help="load concepts/*.md into drillable cards")
    conc.add_argument("--quiet", action="store_true")
    conc.set_defaults(func=cmd_concepts)

    rev = sub.add_parser("revise", help="spaced-repetition drill over concept cards")
    rev.add_argument("--count", type=int, default=5)
    rev.add_argument("--competency", help="restrict to one competency area")
    rev.add_argument("--track", choices=sorted(concepts.TRACKS), help="restrict to one track")
    rev.add_argument("-i", "--interactive", action="store_true", help="reveal and grade inline")
    rev.set_defaults(func=cmd_revise)

    grd = sub.add_parser("grade", help="record a review outcome for one card")
    grd.add_argument("concept_id")
    grd.add_argument("grade", type=int, choices=[0, 1, 2, 3])
    grd.set_defaults(func=cmd_grade)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
