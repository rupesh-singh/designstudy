"""Render the daily digest as a self-contained HTML page."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from jinja2 import Template

from . import concepts, db
from .config import COMPETENCIES, OUT_DIR, SOURCES

TEMPLATE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Engineering Digest &mdash; {{ date }}</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--fg:#e6e9ef;--mut:#98a2b3;--acc:#7aa2f7;--bd:#242832;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 -apple-system,Segoe UI,Roboto,sans-serif;padding:48px 20px}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}
.sub{color:var(--mut);font-size:14px;margin-bottom:32px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:24px;margin-bottom:24px}
.meta{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.tag{font-size:11px;letter-spacing:.4px;text-transform:uppercase;background:#1f2430;color:var(--acc);border:1px solid var(--bd);padding:3px 9px;border-radius:99px}
.tag.src{color:#c3cad9}
.tag.score{color:#9ece6a}
h2{font-size:20px;margin:0 0 10px;line-height:1.35}
h2 a{color:var(--fg);text-decoration:none}
h2 a:hover{color:var(--acc)}
.why{color:var(--mut);font-size:14px;font-style:italic;margin-bottom:16px}
.sum{color:#c3cad9;font-size:15px;margin-bottom:18px}
.qs{border-top:1px solid var(--bd);padding-top:16px}
.qs strong{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut)}
.qs ol{margin:10px 0 0;padding-left:20px}
.qs li{margin-bottom:8px;font-size:14.5px}
textarea{width:100%;margin-top:14px;background:#0f1115;color:var(--fg);border:1px solid var(--bd);border-radius:8px;padding:12px;font:14px/1.6 inherit;resize:vertical;min-height:90px}
.go{display:inline-block;margin-top:16px;background:var(--acc);color:#0f1115;font-weight:600;font-size:14px;padding:9px 18px;border-radius:8px;text-decoration:none}
.cov{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:20px 24px;font-size:13px;color:var(--mut)}
.cov h3{font-size:12px;text-transform:uppercase;letter-spacing:.6px;margin:0 0 12px;color:var(--mut)}
.bar{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.bar span:last-child{color:#c3cad9;font-variant-numeric:tabular-nums}
.empty{text-align:center;color:var(--mut);padding:40px}
h3.sec{font-size:13px;text-transform:uppercase;letter-spacing:.8px;color:var(--mut);margin:40px 0 16px;padding-top:24px;border-top:1px solid var(--bd)}
details.card{padding:20px 24px}
details.card summary{cursor:pointer;font-size:17px;font-weight:600;list-style:none;outline:none}
details.card summary::-webkit-details-marker{display:none}
details.card summary::before{content:'\\25B8 ';color:var(--acc)}
details.card[open] summary::before{content:'\\25BE '}
.cardmeta{color:var(--mut);font-size:12px;margin:6px 0 0 14px}
.answer{border-top:1px solid var(--bd);margin-top:16px;padding-top:16px;font-size:14.5px;color:#c3cad9}
.answer strong{color:var(--fg)}
.answer ul{padding-left:20px;margin:8px 0}
.answer li{margin-bottom:5px}
.answer p{margin:10px 0}
.gradecmd{margin-top:14px;font-size:12px;color:var(--mut);font-family:Consolas,monospace;background:#0f1115;border:1px solid var(--bd);border-radius:6px;padding:8px 10px}
</style></head><body><div class="wrap">
<h1>Daily Engineering Digest</h1>
<div class="sub">{{ date }} &middot; {{ articles|length }} article(s) &middot; from {{ source_count }} engineering blogs{% if cards %} &middot; {{ cards|length }} concept(s) to revise{% endif %}</div>

{% if articles %}<h3 class="sec" style="border:0;margin-top:0;padding-top:0">Today's reading</h3>{% endif %}

{% if not articles %}
<div class="card empty">No articles cleared the quality bar today.<br>Run <code>python -m daily_digest.cli run</code> after new posts land.</div>
{% endif %}

{% for a in articles %}
<div class="card">
  <div class="meta">
    <span class="tag src">{{ a.source_name }}</span>
    {% if a.competency %}<span class="tag">{{ a.competency.replace('-',' ') }}</span>{% endif %}
    <span class="tag score">{{ '%.1f'|format(a.final_score or 0) }}/10</span>
    {% if a.word_count %}<span class="tag src">{{ a.word_count }} words</span>{% endif %}
    {% if a.is_backlog %}<span class="tag src">from backlog</span>{% endif %}
  </div>
  <h2><a href="{{ a.url }}" target="_blank" rel="noopener">{{ a.title }}</a></h2>
  {% if a.llm_reason %}<div class="why">{{ a.llm_reason }}</div>{% endif %}
  {% if a.summary %}<div class="sum">{{ a.summary[:320] }}{% if a.summary|length > 320 %}&hellip;{% endif %}</div>{% endif %}
  <a class="go" href="{{ a.url }}" target="_blank" rel="noopener">Read article &rarr;</a>
  {% if a.questions %}
  <div class="qs" style="margin-top:20px">
    <strong>Answer after reading (no peeking)</strong>
    <ol>{% for q in a.questions %}<li>{{ q }}</li>{% endfor %}</ol>
    <textarea placeholder="Your design notes&hellip; (copy into your notes app &mdash; this box does not save in v0)"></textarea>
  </div>
  {% endif %}
</div>
{% endfor %}

{% if cards %}
<h3 class="sec">Revision &mdash; {{ cards|length }} concept(s) due</h3>
{% for c in cards %}
<details class="card">
  <summary>{{ c.name }}</summary>
  <div class="cardmeta">{{ c.file_title }} &middot; {{ c.section }}{% if c.reps == 0 %} &middot; new{% else %} &middot; rep {{ c.reps }}{% endif %}</div>
  <div class="answer">{{ c.html|safe }}</div>
  <div class="gradecmd">python -m daily_digest.cli grade {{ c.id }} &lt;0=again 1=hard 2=good 3=easy&gt;</div>
</details>
{% endfor %}
{% endif %}

<div class="cov">
  <h3>Competency coverage &mdash; {{ covered }}/{{ total_comp }} areas touched</h3>
  {% for name, n in coverage %}
  <div class="bar"><span>{{ name.replace('-',' ') }}</span><span>{{ '\u25a0' * n if n else '\u00b7' }} {{ n }}</span></div>
  {% endfor %}
</div>
</div></body></html>"""
)


def _is_backlog(row: sqlite3.Row) -> bool:
    from .rank import _is_fresh

    return not _is_fresh(row["published_at"])


def render(articles: list[sqlite3.Row], cards: list[sqlite3.Row] | None = None,
           verbose: bool = True) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "index.html"

    prepared = []
    for row in articles:
        data = dict(row)
        try:
            data["questions"] = json.loads(row["llm_questions"] or "[]")
        except (json.JSONDecodeError, TypeError):
            data["questions"] = []
        data["is_backlog"] = _is_backlog(row)
        prepared.append(data)

    prepared_cards = []
    for row in cards or []:
        data = dict(row)
        data["html"] = concepts.card_to_html(row["body"])
        prepared_cards.append(data)

    with db.connect() as conn:
        coverage_map = db.competency_coverage(conn)

    coverage = sorted(
        ((name, coverage_map.get(name, 0)) for name in COMPETENCIES),
        key=lambda kv: (-kv[1], kv[0]),
    )

    html = TEMPLATE.render(
        date=datetime.now(timezone.utc).strftime("%A, %d %B %Y"),
        articles=prepared,
        cards=prepared_cards,
        source_count=len(SOURCES),
        coverage=coverage,
        covered=sum(1 for _, n in coverage if n > 0),
        total_comp=len(COMPETENCIES),
    )
    out_path.write_text(html, encoding="utf-8")
    if verbose:
        print(f"  digest written to {out_path}")
    return str(out_path)
