# Agentic AI Mastery — Index

An exhaustive, revision-oriented reference for **software engineers** who design,
build, and operate agentic AI systems — aimed at Staff/Principal interviews.

Same five-part card format as the system-design track — **What / Use when /
Advantages / Tradeoffs / Staff signal** — so both sets drill identically.

## The framing that makes this track coherent

You are not being evaluated as an ML researcher. You are being evaluated as an
engineer who has taken a dependency on something **non-deterministic, expensive,
rate-limited, occasionally unavailable, and silently replaced by its vendor**.

Nearly every good answer in this space follows from that sentence. Model
internals appear here only where they change an engineering decision — KV cache
because it explains latency and memory ceilings, tokenization because it
explains cost, prefill/decode because it explains throughput. No training math.

> This is a fast-moving field. The architectural patterns here are durable;
> specific product capabilities, limits, and pricing change constantly. Verify
> version-specific details before relying on them.

---

## Files

| # | File | Area |
|---|---|---|
| A1 | [LLM Foundations for Engineers](a01-llm-foundations-for-engineers.md) | Tokens, context, KV cache, TTFT/ITL, structured output, caching, cost |
| A2 | [Prompting & Context Engineering](a02-prompting-and-context-engineering.md) | Roles, CoT, context budgeting, compaction, prompt versioning |
| A3 | [Retrieval & RAG](a03-retrieval-and-rag.md) | Chunking, embeddings, hybrid search, reranking, permissions, eval |
| A4 | [Agent Architectures](a04-agent-architectures.md) | Workflow vs agent, loops, planning, termination, HITL, durability |
| A5 | [Tools & Integration](a05-tools-and-integration.md) | Function calling, schema design, sandboxing, MCP, idempotency |
| A6 | [Memory & State](a06-memory-and-state.md) | Short/long-term memory, summarization, checkpointing, isolation |
| A7 | [Evaluation & Experimentation](a07-evaluation-and-experimentation.md) | Eval sets, LLM-as-judge, trajectory eval, CI gates, flywheel |
| A8 | [Production Reliability](a08-production-reliability.md) | Fallbacks, rate limits, caching, tracing, cost control, incidents |
| A9 | [Safety & Security](a09-safety-and-security.md) | Prompt injection, lethal trifecta, permissions, sandboxing, tenancy |
| A10 | [Model Adaptation](a10-model-adaptation.md) | Prompt vs RAG vs fine-tune, LoRA, distillation, quantization |
| A11 | [Inference Infrastructure](a11-inference-infrastructure.md) | Serving, batching, GPU sizing, autoscaling, cost levers |
| A12 | [Multi-Agent Systems](a12-multi-agent-systems.md) | Topologies, handoffs, coordination, cost/latency multiplication |
| A13 | [Interview Playbook](a13-agentic-interview-playbook.md) | Structure, estimation, reference designs, failure modes |

---

## The eight ideas that carry the most interview weight

If you internalize nothing else:

1. **Workflow vs agent.** Deterministic control flow is cheaper, faster,
   testable, and debuggable. Saying "this doesn't need an agent" is a strength,
   not a cop-out. Model-driven control flow is a cost you justify.
2. **Context is a budgeted resource, not a string.** Allocate it deliberately
   across instructions, tools, retrieval, history, and scratchpad. Decide what
   gets dropped first.
3. **Agent loop cost grows faster than linearly.** Each step resends accumulated
   context. This is the number one production cost surprise. Compaction,
   context isolation, prefix caching, and step caps are the mitigations.
4. **Most RAG failures are retrieval failures.** Evaluate retrieval separately
   from generation, or you will tune the wrong component forever.
5. **The model never executes anything.** It emits a structured call; your
   runtime validates and executes it. Every permission, sandbox, and idempotency
   control lives on your side of that boundary.
6. **Prompt-level defenses are not security controls.** Against injection you
   need trust boundaries, least-privilege tools, and egress restrictions — not
   politer instructions.
7. **No eval set, no ship.** LLM systems have no unit tests by default. The eval
   suite plus a CI gate is the engineering practice that makes iteration safe.
8. **Your model will change under you.** Providers deprecate and silently update.
   Version prompt+model+tools together, pin what you can, and monitor for
   quality drift with no deploy.

---

## How to use this

Same method as the system-design track — recall, don't re-read:

1. Skim every file's quick-reference table once to map the terrain.
2. Answer each file's drill questions **from memory** before opening it.
3. Let spaced repetition schedule the rest.
4. Build something small end-to-end. This track punishes purely theoretical
   knowledge harder than system design does; a single real agent with a real
   eval set teaches more than any amount of reading.

### Drill this track

```powershell
python -m daily_digest.cli concepts                      # load/refresh cards
python -m daily_digest.cli revise --track agentic-ai -i  # drill this track only
```

Omit `--track` to interleave both tracks, which is usually better once you've
done a first pass on each — interleaving improves discrimination between
similar concepts.

### Suggested 6-week rotation

| Week | Focus | Paired practice |
|---|---|---|
| 1 | A1, A2 | Compute cost/latency for a real agent turn end to end |
| 2 | A3 | Build a small RAG pipeline; measure retrieval recall separately |
| 3 | A4, A5 | Design one task as both a workflow and an agent; compare |
| 4 | A6, A7 | Write an eval suite with a CI gate for something you built |
| 5 | A8, A9 | Threat-model your design; add cost caps and guardrails |
| 6 | A10–A13 | Timed mock interviews on the reference designs |

---

## Competency map

Used by the drill filter (`--competency`):

| Competency | File |
|---|---|
| llm-foundations | A1 |
| context-engineering | A2 |
| retrieval-and-rag | A3 |
| agent-architecture | A4, A13 |
| tools-and-integration | A5 |
| memory-and-state | A6 |
| evaluation | A7 |
| production-reliability | A8 |
| safety-and-security | A9 |
| model-adaptation | A10 |
| inference-infra | A11 |
| multi-agent | A12 |

---

## Relationship to the system-design track

Agentic systems are distributed systems. These carry over directly from
[concepts/](../concepts/00-index.md):

- **Idempotency, retries, backoff** → tool calls with side effects
- **Circuit breakers, bulkheads, fallbacks** → model provider failures
- **Rate limiting, backpressure, queueing** → token quotas and expensive calls
- **Caching patterns and invalidation** → prompt, semantic, and retrieval caches
- **Multi-tenancy and isolation** → per-tenant memory, indexes, and caches
- **Observability, SLOs, tracing** → agent run traces and quality monitoring
- **Saga / compensating transactions** → undoing partially completed agent work
- **Durable execution and checkpointing** → resumable long-running agents

Strong candidates explicitly reuse this vocabulary. An agent that calls a
payment API is a distributed transaction problem, and saying so is worth more
than any framework name.
