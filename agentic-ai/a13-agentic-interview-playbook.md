# A13. The Agentic AI Interview Playbook

Everything else in this track is knowledge. This file is judgment: how to run an
agentic-system design interview, and what separates a Staff/Principal answer
from an enthusiastic one.

The core reframe: **you are being evaluated as a software engineer, not as an ML
person.** The model is a dependency — non-deterministic, expensive, rate-limited,
occasionally unavailable, and periodically replaced without your consent. Almost
every good answer follows from taking that seriously.

---

## The bar

| Dimension | Weaker answer | Staff/Principal answer |
|---|---|---|
| Framing | "I'll use an agent with these tools" | Asks whether an agent is warranted at all; often proposes a workflow |
| Control flow | Lets the model decide everything | Puts the model where judgment is needed, code everywhere else |
| Context | "Put it in the prompt" | Treats context as a budgeted resource with an allocation policy |
| Retrieval | "Vector DB" | Picks retrieval per data shape; knows SQL beats embeddings for structured filters |
| Tools | Lists tools | Designs schemas, permissions, idempotency, and error surfaces |
| Failure | "Add retries" | Enumerates agent-specific failure modes: loops, truncation, bad tool args, injection |
| Evaluation | "We'll check quality" | Defines the eval set, the metric, the CI gate, and the regression story |
| Cost | Rarely mentioned | Computes cost per task and names the dominant driver |
| Security | "Filter bad content" | Reasons about trust boundaries and privilege, not prompt-level pleading |
| Evolution | Designs for today's model | Plans for model deprecation and silent regression |

The single highest-signal habit is the same as in system design: **commit to a
choice, name its trigger condition, and name its reversal condition.** "I'd start
with a fixed three-step workflow. If we find the task genuinely needs unbounded
tool sequences — say, when users ask questions we can't enumerate — I'd move the
middle step to an agent loop with a six-step cap."

---

## Interview structure (45 min)

**1. Requirements — 6–8 min.** What task, for whom, at what volume?
Latency expectation (interactive vs async)? Accuracy bar and what a wrong
answer costs? Does it *act* (side effects) or only *inform*? Who are the users
and can they see each other's data? Budget?

The question that most reshapes the design: **what is the cost of being wrong?**
An agent that drafts a summary and one that issues refunds are different
systems, and the difference is approval gates and permissions, not prompting.

**2. Decide agent vs workflow — 3–5 min.** Explicitly. Out loud. Justify.

**3. High-level architecture — 8–10 min.** Client → orchestration → model
provider(s), plus tools, retrieval, memory, guardrails, and the trace/eval
pipeline. Draw the loop and its termination conditions.

**4. Deep dive — 12–15 min.** Usually retrieval quality, tool design, context
management, or eval. Go where the risk concentrates.

**5. Evaluation, safety, cost, operations — 8–10 min.** Do not let this get
squeezed; it is where seniority shows. If time is short, say "I want to reserve
five minutes for evaluation and failure modes" and take it.

---

## The decision that opens most interviews: agent or workflow?

Use a **workflow** (deterministic control flow, model used for discrete steps)
when the task decomposes predictably. It is cheaper, faster, testable,
debuggable, and it fails in ways you can enumerate.

Use an **agent** (model decides the sequence) when the space of required steps
genuinely cannot be enumerated in advance, the environment gives feedback worth
reacting to, and the value of solving open-ended cases exceeds the cost and
unpredictability.

The strongest thing a candidate can say — and most don't — is: **"I don't think
this needs an agent."** Most production "agents" are three prompts and a
conditional. Proposing a workflow with one model-driven step, and explaining the
condition under which you'd upgrade it, reads as experience.

---

## Cost and latency estimation kit

You will be asked "what does this cost?" Know the shape.

**Per-call cost** ≈ (input tokens × input rate) + (output tokens × output rate),
with cached input typically much cheaper than fresh input. Output tokens
dominate latency; input tokens dominate cost in RAG-heavy systems.

**Per-task cost** = per-call cost × number of model calls in the loop. This is
where agents surprise people: a 6-step loop that re-sends growing context is not
6× a single call, it's closer to quadratic in context growth, because each step
resends the accumulated history.

**That quadratic growth is the single most important cost insight in agentic
systems.** Mitigations: compaction, externalizing state out of context,
subagents with isolated context, prompt caching on the stable prefix, and step
caps.

**Latency budget for one agent turn:** network + queue wait + prefill (scales
with input length) + decode (scales with output length) + tool execution +
retrieval. Decode is usually the floor for long answers; streaming hides it.
Tool calls often dominate wall-clock in real agents.

**Fan-out multipliers to watch:** self-consistency (×N), multi-agent (×agents),
reflection loops (×iterations), reranking (extra model calls per query).

---

## Reference designs

**Customer support agent.** Retrieval over help content + account tools; strict
per-user permission filtering on retrieval; read-only tools by default with
approval gates for refunds/cancellations; escalation to human on low confidence
or explicit request; containment rate and escalation rate as headline metrics;
prompt injection risk via user-submitted attachments and ticket history.

**Coding agent.** Sandboxed execution with no network by default; tests as the
verification signal (the rare case with a genuine automated reward); file-level
context retrieval rather than whole-repo stuffing; iteration cap; diff review
before commit; indirect injection risk from repository content and dependencies.

**Research / deep-research agent.** Planner + parallel search subagents with
isolated contexts + synthesis step; citation requirement with verification
against sources; breadth/depth caps; strong candidate for parallel subagents
because subtasks are independent and context-heavy.

**Data analyst agent.** Text-to-SQL against a governed schema; read-only
credentials; query cost limits and row caps; schema retrieval rather than schema
stuffing; validate SQL before execution; return results plus the query for
auditability. Note that this is retrieval over *structured* data — vector search
is the wrong tool.

**Document processing pipeline.** Usually a workflow, not an agent: extract →
validate → route → human review on low confidence. High volume makes cost per
document the binding constraint; a small fine-tuned or distilled model often
wins here.

---

## Failure modes to name unprompted

Agent-specific, beyond ordinary distributed-systems failures:

- **Infinite or repeating loops** — same tool call repeatedly; needs loop
  detection and a hard step cap. Also a cost incident, not just a bug.
- **Context overflow** — history plus tool results exceed the window; needs a
  truncation policy that drops the right things.
- **Context degradation** — quality falls as context grows, well before the
  limit.
- **Bad tool arguments** — hallucinated IDs, wrong enum values; needs schema
  validation and actionable error messages back to the model.
- **Silent tool failure** — tool returns an error string the model treats as
  data and confidently reports success.
- **Retrieval miss** — the answer wasn't retrieved, so the model invents one.
- **Retrieved-but-ignored** — right chunk present, model still answers wrong.
- **Stale memory / stale cache** — the system confidently uses outdated facts.
- **Indirect prompt injection** — instructions embedded in fetched content.
- **Cross-tenant leakage** — via shared semantic cache, memory store, or an
  unfiltered index.
- **Model deprecation / silent regression** — provider updates the model and
  quality shifts with no code change on your side.
- **Runaway cost** — a loop, a retry storm, or a large-context request pattern
  that quietly multiplies spend.

Naming the **detection signal** for each is the staff move: loop rate, step-count
distribution, truncation rate, tool error rate, groundedness score, cost per
task, refusal rate.

---

## Evaluation: the section that decides the interview

If you say nothing else about evaluation, say this: **build the eval set before
building the feature, and gate deploys on it.**

- Start with 30–50 real examples with known-good outcomes; grow from production
  failures. A handful of hand-picked demos proves nothing.
- Prefer deterministic assertions where possible (valid schema, cited a source,
  called the right tool, query returned rows) over LLM judgment.
- Use LLM-as-judge for what can't be asserted, but calibrate it against human
  labels and know its biases: position, verbosity, self-preference.
- For agents, evaluate the **trajectory** as well as the outcome — the right
  answer via a wrong path won't generalize.
- Track cost and latency as eval dimensions, not afterthoughts.
- Re-run on every prompt, model, and tool change; non-determinism means you need
  repeated runs, not a single pass.
- Mine production traces into new test cases. That flywheel *is* the moat.

---

## Tradeoff cheat sheet

- **RAG vs long context vs fine-tune** → freshness/auditability/scale vs
  simplicity vs per-token cost and format control.
- **Agent vs workflow** → open-ended capability vs cost, latency, testability.
- **Single agent with many tools vs multi-agent** → simplicity and shared
  context vs context isolation and parallelism, paid in cost and debuggability.
- **Big model vs small model + routing** → quality ceiling vs cost per task.
- **More context vs better retrieval** → simplicity vs cost and quality at scale.
- **Semantic cache vs exact cache** → hit rate vs correctness risk.
- **Managed API vs self-hosted** → speed and capability vs cost at volume,
  compliance, and control.
- **Autonomy vs approval gates** → throughput vs blast radius.
- **Streaming vs batch** → perceived latency vs throughput and cost.
- **Prompt-only vs fine-tune** → iteration speed vs per-request cost and
  consistency.

---

## Things that quietly lose points

- Proposing multi-agent for a task one agent (or one prompt) could do.
- Saying "we'll use RAG" without discussing chunking, permissions, or eval.
- Vector search for structured/filterable data that belongs in SQL.
- Claiming prompt instructions will prevent prompt injection.
- Ignoring per-user permissions in retrieval — a data breach waiting to happen.
- No termination condition on the agent loop.
- No eval strategy, or "we'll have humans check it" with no sampling plan.
- Ignoring cost entirely, then proposing self-consistency with 5 samples.
- Treating the model as deterministic and testable like ordinary code.
- Assuming the model executes tools (it emits calls; your runtime executes).
- No plan for the provider deprecating or silently updating the model.
- Logging full prompts and outputs with no thought to PII or retention.

---

## Drill questions

1. Given a support-automation brief, argue for a workflow instead of an agent —
   then state the condition that would change your mind.
2. Explain precisely why an agent loop's cost grows faster than linearly in
   steps, and give three mitigations.
3. A RAG system returns the correct document but the answer is still wrong. Walk
   through your diagnosis.
4. Design permission enforcement for retrieval in a multi-tenant assistant.
   Where exactly is the filter applied, and why not later?
5. Your agent reads user-submitted web pages and can send email. Name the risk
   and the controls, without relying on prompt instructions.
6. Define the eval suite for a text-to-SQL agent: datasets, metrics, CI gate.
7. Your provider deprecates the model you launched on. Describe the migration.
8. Quality dropped 10% with no deploy. How do you confirm it and respond?
9. When would you fine-tune instead of improving retrieval? Give the numbers
   that would justify it.
10. Design a cost guardrail preventing a single user from spending $1,000 in a
    day, without breaking legitimate heavy use.
11. An agent repeats the same tool call forever. Give three independent
    mechanisms that stop it, and where each belongs.
12. Justify splitting one agent into three — then argue the opposite.
