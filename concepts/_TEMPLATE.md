# Authoring template — read before writing any concept file

Every concept in this reference uses the **same five-part card**. Consistency is
what makes the set drillable; do not invent alternate structures.

## Card format

```markdown
### <Concept name>
**What.** One or two precise sentences. Define the mechanism, not the marketing.
**Use when.** Concrete triggering conditions — the situation that makes you reach
for this. Name real systems that use it where it sharpens the point.
**Advantages.**
- Concrete, specific benefit (include numbers/orders of magnitude where real)
- ...
**Tradeoffs.**
- Concrete cost, failure mode, or operational burden
- ...
**Staff signal.** The non-obvious insight that separates a staff/principal answer
from a senior one. Usually: a second-order effect, a failure mode under load, a
cost/organizational consequence, or knowing when *not* to use it.
```

## File structure

1. `# <N>. <Title>` heading
2. One-paragraph orientation: why this area exists, what problem class it solves.
3. **Quick reference table** — every concept in the file, one row each:
   `| Concept | One-line role | Reach for it when |`
4. The concept cards, grouped under `## <Sub-area>` headings.
5. `## Common interview traps` — 5–10 bullets of specific mistakes candidates make
   in this area, each with the correction.
6. `## Drill questions` — 8–12 questions that force recall and tradeoff reasoning,
   not definitions. Prefer "when would you choose X over Y and why" and
   "what breaks first when ...".

## Quality bar

- **Be technically precise.** This is memorized material; an error propagates.
  Prefer omitting a claim to guessing. Do not invent benchmark numbers — use
  orders of magnitude and label them as approximate.
- **Write original prose.** Explain concepts in your own words. Do not reproduce
  text, phrasing, or example wording from any book or article. These are
  industry-standard technical concepts; the expression must be yours.
- **Be dense.** No filler, no throat-clearing, no "in today's world". Every
  sentence should carry information a candidate could be asked about.
- **Name real systems** (PostgreSQL, Kafka, DynamoDB, Cassandra, Spanner, etc.)
  when they make a tradeoff concrete. Accuracy matters — only cite behaviour you
  are confident about.
- **Always state the tradeoff.** A concept without its cost is not revision
  material. If something looks free, explain where the cost is actually paid.
- Aim for roughly 1,800–2,600 words per file.
