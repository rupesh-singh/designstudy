# Daily Engineering Digest + Mastery Tracks

Three things in one repo, deliberately coupled:

1. **Daily digest** — two curated system-design articles a day from 11 working
   engineering blogs, scored for depth. Concrete, current practice.
2. **System design track** — an exhaustive revision set in [concepts/](concepts/).
3. **Agentic AI track** — a parallel set in [agentic-ai/](agentic-ai/), written
   for engineers who build and operate agentic systems. Includes a narrative
   [guide/](agentic-ai/guide/00-overview.md) that explains the whole track as one
   connected, build-and-deploy story — from tokens to shipping.

Both tracks use the same card format and the same spaced-repetition engine, and
can be drilled together or separately.

## The reference tracks

| Track | Entry point | Scope |
|---|---|---|
| System design | [concepts/00-index.md](concepts/00-index.md) | Storage, replication, partitioning, transactions, consensus, streaming, caching, APIs, resilience, architecture, observability, security, algorithms |
| Agentic AI | [agentic-ai/a00-index.md](agentic-ai/a00-index.md) | LLM foundations, context engineering, RAG, agent architectures, tools/MCP, memory, evaluation, production reliability, safety, adaptation, inference infra, multi-agent |

Every concept uses the same five-part card:

**What** · **Use when** · **Advantages** · **Tradeoffs** · **Staff signal**

The last field is the point — it's the second-order insight that separates a
staff answer from a senior one. Each file also ends with common interview traps
and drill questions.

The agentic track is written from a **software engineering** perspective: the
model is treated as a non-deterministic, expensive, rate-limited dependency, and
model internals appear only where they change an architecture decision.

## Spaced repetition

```powershell
.\.venv\Scripts\python.exe -m daily_digest.cli concepts        # load cards
.\.venv\Scripts\python.exe -m daily_digest.cli revise -i       # drill interactively
```

Restrict to one track or competency:

```powershell
... cli.py revise --track agentic-ai -i
... cli.py revise --track system-design --competency caching -i
```

`revise -i` shows a concept name, waits for you to recall it aloud, reveals the
card, then asks you to grade yourself 0–3. An SM-2 style scheduler pushes cards
you know into the future and brings back the ones you fail. Cards you've never
seen and cards you've lapsed on surface first.

Grade non-interactively (e.g. from the digest page) with:

```powershell
... cli.py grade <concept-id> <0=again 1=hard 2=good 3=easy>
```

Reference files are the source of truth — edit the markdown, re-run `concepts`,
and your review schedule is preserved.

## Why this exists

Roughly 4 out of 5 posts on these blogs are product launches, release notes, or
company news. A plain RSS reader buries you in that. This pipeline throws the
noise away and hands you two things worth reading, balanced across a competency
taxonomy so you build breadth over months instead of re-reading your favourite
topic.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m daily_digest.cli run --open
```

Then schedule it:

```powershell
.\setup_task.ps1 -Time 07:30
```

Set `out\index.html` as your browser home page or new-tab page. That is the
whole delivery mechanism — the digest is waiting when you open a browser.

## Enabling LLM ranking (recommended)

Without an API key the system falls back to heuristic scoring, which works but
cannot tell "Introducing Kitesurf" from a real architecture deep-dive as
reliably. Create a `.env` file:

```
DIGEST_LLM_API_KEY=sk-...
DIGEST_LLM_BASE_URL=https://api.openai.com/v1
DIGEST_LLM_MODEL=gpt-4o-mini
```

Any OpenAI-compatible endpoint works (OpenAI, Azure OpenAI, GitHub Models,
Ollama). Only articles that survive the free heuristic prefilter reach the LLM —
typically 20-40 per day, so cost stays near zero.

## Commands

| Command | Purpose |
|---|---|
| `cli.py run` | Full pipeline: collect → extract → prefilter → score → digest |
| `cli.py concepts` | Load/refresh concept cards from both tracks |
| `cli.py revise -i` | Spaced-repetition drill (add `--track` / `--competency`) |
| `cli.py grade <id> <0-3>` | Record a review outcome |
| `cli.py doctor` | Per-source health check; exits 1 if a source breaks |
| `cli.py stats` | Pass rates per source and competency coverage |
| `cli.py backfill --limit 150` | Extract and score more of the stored backlog |
| `cli.py reset` | Clear scores to retune filters without refetching |
| `cli.py prune` | Delete rows from deconfigured sources |

Useful flags on `run`: `--count 3`, `--open`, `--quiet`, `--revise-count 5`,
`--no-revision`.

Run `doctor` occasionally. Feeds rot silently — a blog changes CMS, adds bot
protection, or moves its RSS path, and you simply stop seeing its articles with
no error. `doctor` distinguishes *blocked* (fetches but no body text) from *low
value* (fetches fine, nothing clears the quality bar), which are very different
problems.

## Source coverage

11 of the 21 blogs from the original wishlist work over plain RSS. The other 10
are listed in `NEEDS_ADAPTER` in [config.py](daily_digest/config.py) with the
specific reason each one fails — 403s and bot protection need a headless
browser; missing RSS needs an HTML adapter.

Two worth calling out:

- **Stripe** — `stripe.com/blog/feed.rss` is the *marketing* blog (event links,
  business trends). The engineering posts live at `/blog/engineering` and have
  no feed. Wiring the marketing feed up looks like it works but yields nothing.
- **OpenAI** — article pages return 403 and the feed carries only 25-word
  teasers, so depth can never be judged from it.

Both were active in an earlier build and produced zero usable articles, which is
exactly the failure mode `doctor` exists to catch.

## How selection works

1. **Collect** — RSS/Atom for 13 sources. Feeds that ship full content inline
   (Medium-hosted: Netflix, Airbnb, Pinterest, Instacart) are read directly,
   which sidesteps Medium's scraping blocks.
2. **Extract** — `trafilatura` pulls body text for the rest. Titles lie; depth
   judgements need the body.
3. **Prefilter (free)** — kills changelogs/hiring/launch posts, drops anything
   under 600 words, and applies soft penalties to launch language. Cuts the pool
   by more than half before any token is spent.
4. **Score** — LLM rates 0–10 on architectural depth and writes three retrieval
   questions. Falls back to heuristics if no key is configured.
5. **Select** — *not* top-2-by-score. Boosts your least-covered competency,
   penalizes recently-served sources, forbids two articles on the same
   competency in one day, and reserves one slot for the backlog so a dry news
   day still produces a full digest.

## Competency coverage

Twelve staff-level areas (distributed systems, storage, caching, queues,
scale/performance, reliability, observability, migrations, architecture/APIs,
security/multi-tenancy, infra/cost, ML systems). The footer of every digest
shows which are under-served, and the selector actively steers toward the gaps.

## Retrieval practice

Each article ships with three questions to answer *after* reading. Reading
without recall is entertainment. In v0 the notes box does not persist — copy
answers into your notes app. Persistence and spaced repetition land in v2.

## Not yet covered

Ten blogs from the wishlist publish no usable RSS and need adapters (v1):
Anthropic, Databricks, Shopify, Snowflake, Confluent, CockroachDB, ClickHouse,
Figma, Uber — plus Stripe's engineering section. Four sit behind bot protection
(OpenAI, Databricks, Snowflake, and Stripe intermittently) and will need a
headless browser. Run `cli.py doctor` for the current list with reasons.

Also planned: archive backfill of classic posts, thumbs-up/skip feedback into
scoring weights, and a spaced-repetition review loop.
