# A8. Production Reliability, Observability & Cost

Running an agent in production is a distributed-systems problem where your most critical dependency — the model — is non-deterministic, expensive, rate-limited, and operated by a third party you do not control. Every reliability pattern from microservices (retries, circuit breakers, fallbacks, observability) applies, but the failure modes are novel: a retry that doubles your bill, a runaway loop that spends thousands of dollars in minutes, a silent model update that shifts behavior without any deployment on your side. This file covers the engineering required to keep agentic systems reliable, observable, and economically viable.

## Quick-reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Model provider as unreliable dependency | Treat the LLM API like any flaky third-party service | Designing agent reliability |
| Timeouts and budgets | Per-step and per-run time/cost limits | Bounding agent execution |
| Retries for LLM calls | When and how to retry safely | Handling transient failures |
| Fallback chains | Degrade gracefully through model tiers | Handling outages and latency spikes |
| Multi-provider abstraction | Swap models without code changes | Avoiding vendor lock-in |
| Rate limits and quota management | Client-side throttling and priority lanes | Operating at scale |
| Capacity planning in tokens | Plan for tokens, not requests | Sizing infrastructure |
| Cost control and budgets | Per-request, per-user, per-tenant spend caps | Preventing bill shock |
| Runaway agent loops | Detect and halt infinite agent iteration | Operational cost safety |
| Caching strategies | Reuse prior results to save cost and latency | High-repetition workloads |
| Queueing and backpressure | Buffer expensive async work | Managing load spikes |
| Graceful degradation | Reduce capability instead of failing | Under pressure or budget constraints |
| Idempotency for side effects | Safe retries for tool-triggered actions | Agents that write, send, or mutate |
| Observability and tracing | Span trees for agent runs | Debugging and cost attribution |
| What to log | Prompts, completions, tool calls, PII tension | Building a debuggable system |
| Replay and debugging | Reproduce failures from traces | Diagnosing production issues |
| Versioning as a unit | Prompt + model + tools as a deployable bundle | Correlating regressions to changes |
| Agent-specific monitoring | Step count, loop rate, truncation rate | Detecting agent-specific pathology |
| SLOs for agentic systems | Define SLIs for non-deterministic output | Setting quality targets |
| Alerting on quality drift | Detect degradation, not just errors | Proactive quality management |
| Incident response for AI | Kill switches, prompt rollback, model pinning | Responding to AI incidents |
| Provider deprecations | Forced model migrations | Operational readiness |
| Self-hosting vs API | Reliability/cost/compliance tradeoff | Infrastructure strategy |

## Reliability patterns

### Model provider as unreliable dependency
**What.** An LLM API has all the failure modes of a third-party service — latency variance (P50 vs P99 can differ by 10×), outages, quota exhaustion, deprecations — plus unique ones: response quality can degrade without any HTTP error. Treat it with the same skepticism as an external payment gateway.
**Use when.** Architecting any production agent system. This framing drives every other decision in this file.
**Advantages.**
- Forces you to build fallbacks, timeouts, and monitoring from day one
- Prevents the naive assumption that "the API will just work"
**Tradeoffs.**
- Adds engineering complexity that feels unnecessary during prototyping
- May lead to over-engineering for low-traffic internal tools
**Staff signal.** The unique risk is that model quality can degrade without any error signal. A 200 OK with a subtly worse response is harder to detect than a 500 error. This is why eval-based monitoring (not just HTTP health checks) is essential.

### Timeouts for LLM calls
**What.** Set per-step timeouts (each individual model call) and per-run budgets (total time for an entire agent task). Streaming complicates timeouts because the connection stays alive while tokens trickle in — you need a "time-to-first-token" timeout, a "maximum inter-token gap" timeout, and an overall wall-clock limit.
**Use when.** Every production LLM call. Unbounded calls will eventually hang during provider issues.
**Advantages.**
- Prevents stuck requests from consuming resources and blocking user-facing latency
- Per-run budgets catch runaway multi-step agents before they accumulate unbounded cost
**Tradeoffs.**
- Aggressive timeouts cause false failures during legitimate slow responses (complex reasoning, large outputs)
- Streaming timeout logic is non-trivial to implement correctly
**Staff signal.** Set the per-run budget as a hard wall-clock limit independent of step-level retries. An agent that retries each step three times may still complete within the per-step timeout but blow through the per-run budget. These are two separate safety nets.

### Retries
**What.** Retry transient failures (429, 500, 503, network errors) with exponential backoff and jitter. Retries are safe only for read-only operations; for calls that trigger tool side effects, you need idempotency guarantees before retrying. Naive retries multiply cost: retrying a $0.05 call three times costs $0.15.
**Use when.** Handling transient provider errors. Never retry on 400 (bad request) or content-policy violations.
**Advantages.**
- Absorbs transient provider instability without user-facing failures
**Tradeoffs.**
- Multiplies token cost per request by the retry count
- Retry storms under widespread outages amplify the problem (use circuit breakers)
- Retrying a non-idempotent tool call (e.g., "send email") causes duplicate side effects
**Staff signal.** Consider retrying with a modified request (e.g., shorter prompt, different temperature) rather than an identical retry. This costs the same but may succeed where a verbatim retry would fail again. This is a "retry with degradation" pattern unique to LLM systems.

### Fallback chains and model routing
**What.** A tiered fallback strategy: primary model → cheaper/smaller model → cached/static response → human escalation. Model routing can also be proactive: route simple queries to small models and complex ones to large models, reducing cost without sacrificing quality.
**Use when.** Designing for high availability and cost optimization simultaneously.
**Advantages.**
- Near-zero downtime: if the primary model is unavailable, users get a degraded but functional response
- Cost-aware routing can cut token spend by 50–70% for workloads with a mix of simple and complex queries
**Tradeoffs.**
- Each fallback tier requires its own prompt tuning, eval, and testing
- Routing logic adds latency and complexity; misrouting complex queries to weak models degrades quality silently
**Staff signal.** The hardest part is the routing decision, not the fallback mechanism. A classifier that routes 10% of complex queries to the small model causes more damage than an occasional outage of the large model. Invest in routing accuracy as a first-class metric.

### Multi-provider abstraction layers
**What.** An abstraction layer that normalizes different model provider APIs behind a common interface, enabling model swaps without code changes.
**Use when.** You use (or plan to use) multiple providers, or want to avoid deep vendor lock-in.
**Advantages.**
- Enables fallback across providers (e.g., OpenAI → Anthropic → self-hosted)
- Simplifies A/B testing across models
**Tradeoffs.**
- Lowest-common-denominator API: you lose provider-specific features (structured output, tool-use formats, caching APIs)
- Prompt behavior varies across models; an abstraction layer that swaps the model without adjusting the prompt gives worse results than tuning per-model
**Staff signal.** The real cost of multi-provider abstraction is not the code — it is maintaining prompt variants and eval suites per model. If you abstract the API but not the prompts, you are not actually portable.

### Rate limits and quota management
**What.** LLM APIs enforce tokens-per-minute (TPM) and requests-per-minute (RPM) limits. Client-side throttling, token-aware request queuing, and priority lanes (urgent user requests preempt batch jobs) prevent 429 errors and ensure fair resource allocation.
**Use when.** Operating at any scale beyond prototyping. Even moderate traffic can hit rate limits with long-context requests.
**Advantages.**
- Prevents cascading 429 failures and retry storms
- Priority lanes ensure interactive users are never starved by background jobs
**Tradeoffs.**
- Token-aware queuing requires estimating token count before sending (prompt token count can be computed; completion token count must be estimated)
- Over-conservative throttling wastes available quota
**Staff signal.** Plan quota in tokens, not requests. A single long-context request can consume as much quota as 50 short ones. Track TPM utilization as your primary capacity metric, not RPM.

### Capacity planning in tokens
**What.** Traditional capacity planning uses requests-per-second. For LLM systems, a "request" can vary from 100 tokens to 100,000 tokens, making RPS meaningless. Plan in tokens per minute (TPM) and compute cost per token across model tiers.
**Use when.** Sizing quota, budgeting, and forecasting for any LLM-backed system.
**Advantages.**
- Accurate cost forecasting; prevents quota exhaustion from a few large requests
**Tradeoffs.**
- Requires instrumentation to track actual token consumption per request class
**Staff signal.** Output tokens are typically 3–6× more expensive than input tokens and have lower throughput limits. A system that generates long outputs (code, reports) hits output token bottlenecks before input token limits. Size for the binding constraint.

## Cost control

### Cost control: budgets and circuit breakers
**What.** Enforce spending limits at multiple granularities: per-request (reject or truncate if estimated cost exceeds threshold), per-user (daily/monthly caps), and per-tenant (contractual limits in multi-tenant systems). Circuit breakers trip when spend rate exceeds a threshold, halting non-essential LLM calls.
**Use when.** Always. Unbounded LLM spend is an existential operational risk.
**Advantages.**
- Prevents runaway costs from bugs, abuse, or unexpected traffic
- Per-tenant caps enable predictable unit economics for SaaS products
**Tradeoffs.**
- Hard caps cause user-facing failures; soft caps with degradation are better UX but harder to implement
- Estimating cost before a call requires token-count estimation, which is approximate
**Staff signal.** Implement the circuit breaker on spend *rate* (dollars per minute), not just cumulative spend. A bug that burns $100/minute will exhaust a $10,000 monthly budget in under two hours. Rate-based detection catches this in minutes.

### Runaway agent loops
**What.** An agent that enters an infinite or near-infinite loop — retrying a failing tool, oscillating between two strategies, or generating unbounded plan steps — is the most common and most expensive production failure mode for agentic systems. A single runaway session can cost hundreds of dollars in minutes.
**Use when.** Designing any autonomous agent. This is not a theoretical risk; it happens routinely.
**Advantages.**
- Awareness motivates hard step-count limits, cost-per-session caps, and loop-detection heuristics
**Tradeoffs.**
- Hard step limits can kill legitimate complex tasks; setting the right limit requires empirical data
- Loop detection heuristics (repeated tool calls, oscillating plans) have false positives
**Staff signal.** Implement three independent safety nets: (1) max step count, (2) max wall-clock time, (3) max cost per session. Any one of them tripping should halt the agent and escalate. Do not rely on a single limit because different failure modes hit different limits first.

### Caching strategies
**What.** Exact-match caching (identical prompt → cached response) is safe and effective for repeated queries. Provider-level prompt prefix caching (shared system-prompt prefix avoids re-processing) reduces latency and cost for prompts with large shared prefixes. Semantic caching (similar-enough prompts → cached response) saves cost but risks returning stale or incorrect answers for subtly different queries.
**Use when.** Exact-match caching for any system with repeated queries. Semantic caching only for low-stakes, high-repetition, read-only workloads with careful similarity threshold tuning.
**Advantages.**
- Exact-match: zero risk, significant savings for repetitive workloads. Prefix caching: up to 80-90% latency reduction on long system prompts (provider-dependent).
**Tradeoffs.**
- Semantic caching has a correctness risk: "What is my balance?" and "What is my spouse's balance?" may be semantically similar but must produce different answers
- Cache invalidation is hard for time-sensitive or personalized content
**Staff signal.** Semantic caching is the most dangerous optimization in LLM systems. It trades correctness for cost. If you must use it, scope it per-user and per-session, and use a high similarity threshold. In multi-tenant systems, a shared semantic cache is a cross-tenant data leakage vector.

### Queueing and backpressure
**What.** For expensive async agent workloads (document processing, code migration), use a job queue with backpressure to prevent overloading the model API. Workers consume jobs at a rate that respects token quotas.
**Use when.** Any batch or async agent workload. Without queuing, a burst of requests exhausts quota and causes cascading failures.
**Advantages.**
- Smooths traffic spikes and prevents quota exhaustion
- Enables fair scheduling across tenants and priority levels
**Tradeoffs.**
- Adds latency (queue wait time) and infrastructure complexity
- Queue depth monitoring is required to detect stalls
**Staff signal.** Set queue depth alerts relative to your processing rate. If the queue grows faster than it drains for more than 5 minutes, you have a capacity problem — alert before the queue overflows, not after.

### Graceful degradation
**What.** When under pressure (quota exhaustion, latency spike, cost cap), degrade capability instead of failing entirely: switch to a smaller model, reduce the number of available tools, shorten context, or disable optional enrichment steps.
**Use when.** Designing the failure modes of your system. Every component should have a defined degraded mode.
**Advantages.**
- Maintains partial functionality during incidents instead of total outage
- Degradation modes are tested in advance, so behavior is predictable
**Tradeoffs.**
- Each degradation mode requires its own testing and eval
- Users may not realize they are receiving degraded responses, leading to silent quality drops
**Staff signal.** Label degraded responses so users (and your monitoring) know when they are receiving them. A "best-effort answer" indicator enables appropriate trust calibration and prevents degraded responses from being treated as authoritative.

### Idempotency for agent side effects
**What.** When an agent triggers external side effects (sending emails, creating tickets, executing trades), those operations must be idempotent to survive retries safely. Use idempotency keys, deduplication windows, and write-ahead logging to ensure exactly-once execution.
**Use when.** Any agent that performs write operations. This is standard distributed-systems practice, but agents make it harder because the LLM may reformulate the request slightly on retry, making deduplication by content hash unreliable.
**Advantages.**
- Safe retries without duplicate side effects
**Tradeoffs.**
- Requires idempotency support in downstream systems (not always available)
- Deduplication by semantic similarity is expensive and unreliable
**Staff signal.** Assign an idempotency key at the *intent* level (e.g., "send user X the order confirmation for order Y"), not at the LLM-call level. If the LLM rephrases the email body on retry, the idempotency key should still match because the intent is the same.

## Observability

### Tracing agent runs
**What.** Model each agent run as a span tree: the root span is the task, child spans are agent steps, and each step contains sub-spans for model calls, tool invocations, and guardrail checks. Attach token counts, cost, latency, model version, and prompt hash to each span.
**Use when.** Every production agent system. Without structured tracing, debugging a multi-step agent failure is forensic archaeology.
**Advantages.**
- Enables per-step cost attribution (which step is expensive?), latency breakdown, and error localization
- Traces are the raw material for the eval flywheel (mining failures into test cases)
**Tradeoffs.**
- High cardinality: a single agent run can generate hundreds of spans, which stresses tracing infrastructure
- Prompt/completion content in spans raises PII and storage cost concerns
**Staff signal.** Index traces by outcome (success/failure, user feedback signal) so you can efficiently query "show me all failed runs in the last 24 hours." Unindexed traces are a write-only archive — useful in theory but unusable in practice.

### What to log
**What.** Log the full prompt, completion, tool arguments, tool results, model version, prompt version, latencies, and token counts. But prompts and completions may contain PII, confidential data, or secrets — creating tension between debuggability and compliance.
**Use when.** Designing your logging pipeline. This decision has legal and operational implications.
**Advantages.**
- Full logs enable deterministic replay and root-cause analysis
**Tradeoffs.**
- PII in logs requires encryption, access control, retention policies, and right-to-deletion support
- Log volume is high (kilobytes per model call vs bytes for traditional API logs)
**Staff signal.** Implement tiered logging: always log metadata (model, version, token count, latency, tool names), and conditionally log content (prompts, completions) with PII redaction and a short retention window. This gives you debugging capability without long-term compliance liability.

### Replay and debugging from traces
**What.** Reproduce a production failure by replaying the same prompts with deterministic tool results (recorded in the trace), isolating whether the failure was due to the model, the tools, or the interaction.
**Use when.** Diagnosing a production incident. Replay is the single most valuable debugging technique for multi-step agents.
**Advantages.**
- Eliminates non-determinism from the debugging loop by fixing tool outputs
- Enables counterfactual testing: "what would have happened with a different prompt?"
**Tradeoffs.**
- Requires comprehensive trace capture including tool results
- Replay is never perfectly deterministic due to model non-determinism, but fixing tools eliminates one major variable
**Staff signal.** Build replay capability from day one. Retrofitting it is extremely expensive. The minimal implementation is: log tool inputs and outputs at each step, then provide a replay mode that substitutes recorded outputs instead of calling real tools.

### Versioning as a deployable unit
**What.** A prompt change, a model change, and a tool schema change can all cause regressions. Version the combination (prompt + model + tool definitions) as a single immutable artifact. Correlate every production trace to this version so regressions can be bisected.
**Use when.** Operating any system where prompts, models, or tools change independently.
**Advantages.**
- Enables precise regression bisection: "quality dropped after version X, which changed the tool schema"
- Prevents the "what changed?" mystery during incidents
**Tradeoffs.**
- Requires a versioning and deployment system for non-code artifacts (prompts are not typically in CI/CD pipelines)
**Staff signal.** The most common cause of "mystery regressions" is an untracked prompt change made directly in a config file. Treat prompt changes with the same rigor as code changes: version control, review, CI eval, staged rollout.

## Monitoring and incident response

### Agent-specific monitoring signals
**What.** Beyond standard API metrics, monitor: step-count distribution (shifts indicate behavioral changes), loop rate (agent repeating the same step), tool error rate, context truncation rate (hitting context window limits), refusal rate (model declining to answer), and empty/invalid output rate.
**Use when.** Operating any agent in production.
**Advantages.**
- These signals catch agent-specific failure modes that HTTP error rates miss entirely
- Step-count distribution shift is the earliest indicator of behavioral regression
**Tradeoffs.**
- Requires custom instrumentation; off-the-shelf APM tools do not track these
**Staff signal.** Alert on step-count P95, not just mean. A shift in P95 step count (e.g., from 5 to 12) often indicates the agent is struggling with a new class of inputs, even if mean step count barely moved.

### SLOs for agentic systems
**What.** Defining SLIs for non-deterministic systems is genuinely hard. Candidate SLIs: task completion rate (fraction of tasks resolved without escalation), P95 latency, cost per successful task, safety violation rate. SLOs are targets on these SLIs (e.g., "95% task completion, P95 < 30s, cost per success < $0.10").
**Use when.** Setting contractual or team commitments for agent quality.
**Advantages.**
- Provides concrete targets that drive engineering priorities
- Enables error-budget-based release decisions
**Tradeoffs.**
- Quality SLIs require eval infrastructure, not just monitoring
- Non-determinism means SLIs have inherent variance; error budgets must be set with this in mind
**Staff signal.** Task completion rate is the SLI that matters most for user trust and business value. Latency and cost SLOs exist to prevent optimizing completion rate by throwing unlimited resources at every request.

### Alerting on quality drift
**What.** Monitor eval metrics (from continuous production eval or online metrics) and alert when they drift below threshold. This catches silent regressions that produce no errors but shift output quality — the most dangerous failure mode.
**Use when.** Operating any system that depends on a model you do not control.
**Advantages.**
- Only mechanism for detecting provider-side model changes and subtle prompt/data drift
**Tradeoffs.**
- Eval-based alerts are noisier than error-based alerts due to metric variance
- Requires continuous eval infrastructure running against production traffic
**Staff signal.** Use a rolling window with a statistical test (e.g., alert when the 7-day rolling average drops more than 2 standard deviations below the 30-day baseline), not a fixed threshold. This adapts to natural variance and catches real drift.

### Incident response for AI systems
**What.** AI-specific incident tools: kill switches (disable the agent, route all traffic to fallback), feature flags (disable specific tools or capabilities), prompt rollback (revert to last-known-good prompt version), and model pinning (force a specific model version regardless of provider default). These must be executable in minutes, not hours.
**Use when.** Designing your incident response playbook for agentic systems.
**Advantages.**
- Reduces mean-time-to-recovery for AI-specific incidents
- Kill switches and prompt rollback do not require code deployments
**Tradeoffs.**
- Kill switches that route to a static fallback may be worse than no response for some use cases
- Model pinning may not be supported by all providers
**Staff signal.** Test your kill switch quarterly. An untested kill switch is indistinguishable from no kill switch. Include it in your incident drills alongside standard infrastructure failover.

### Provider deprecations and forced migrations
**What.** Model providers deprecate model versions with finite notice (weeks to months). Treat these as planned operational events: evaluate the replacement model on your eval suite, update prompts if needed, canary deploy, and cut over — similar to a database migration.
**Use when.** You receive a deprecation notice, or proactively before a model version reaches end-of-life.
**Advantages.**
- Planned migration avoids emergency scrambles when the old model stops serving
**Tradeoffs.**
- Replacement models may have different behavior requiring prompt adjustments
- Eval suite must be current; stale evals give false confidence
**Staff signal.** Maintain a "model migration runbook" with checkpoints: eval on new model, prompt adjustment if needed, canary at 5% traffic, expand to 50%, full cutover. Track each provider's deprecation timeline in your operational calendar.

### Self-hosting vs API
**What.** Self-hosting models gives you control over version, availability, and data residency but requires GPU infrastructure, model serving expertise, and ongoing maintenance. APIs provide zero-ops model access but introduce dependency risk, data handling concerns, and rate limits.
**Use when.** Making infrastructure strategy decisions. Neither is universally correct.
**Advantages.**
- Self-hosting: version pinning, no rate limits, data stays on-premises, customization. API: no GPU management, instant access to frontier models, pay-per-use.
**Tradeoffs.**
- Self-hosting: significant infrastructure cost (GPUs are expensive and scarce), operational burden, model quality lag (frontier models reach APIs first). API: vendor lock-in, compliance risk, cost unpredictability at scale.
**Staff signal.** The breakeven is workload-dependent: high-volume, predictable workloads with a model that is good enough often favor self-hosting; low-volume or frontier-quality requirements favor APIs. Run the cost analysis at your actual token volume, not at list price.

## Common interview traps

- **Treating LLM API calls like database queries.** They are orders of magnitude more expensive, slower, and less reliable. Different retry, timeout, and caching strategies apply.
- **Retrying without considering cost.** Three retries on a $0.10 call cost $0.30 and may exceed your per-request budget.
- **Ignoring the runaway loop problem.** "We set max_tokens" does not prevent an agent from looping; it only limits each individual response.
- **Believing temperature=0 eliminates the need for variance-aware monitoring.** Provider-side changes can shift behavior regardless.
- **Caching semantically similar prompts without considering correctness.** "Transfer $100 to Alice" and "Transfer $100 to Bob" may be semantically similar but must produce different actions.
- **Monitoring only HTTP errors for an LLM system.** A 200 OK with a bad response is the common failure mode, not a 500.
- **Versioning prompts separately from model versions.** A prompt optimized for one model may perform poorly on another; they must be versioned together.
- **Setting SLOs based on deterministic system expectations.** Agent output has inherent variance; SLOs must accommodate this.

## Drill questions

1. Your agent's cost per successful task has doubled over the last month, but task completion rate is unchanged. What are the likely causes and how do you diagnose?
2. Your model provider announces a new default version for your model. Walk through the steps from notification to full production cutover.
3. Design the timeout strategy for a streaming agent that takes 5–30 seconds per step and executes 3–10 steps per task.
4. Your semantic cache is returning answers meant for user A to user B. How did this happen and how do you prevent it?
5. An agent entered a 200-step loop on a single user task and spent $300 before being detected. Design the safety nets that would have caught this in under 60 seconds.
6. You need to add a kill switch to your agent system. What does the architecture look like, and what does traffic see when the kill switch is activated?
7. Your observability system logs full prompts and completions. A compliance audit flags PII retention. How do you balance debuggability with data protection?
8. When would you choose self-hosting over an API provider, and what is the minimum scale at which self-hosting is typically cost-effective?
9. Your agent has a P95 step count of 5, but this week it shifted to 12. No code changes were deployed. What do you investigate?
10. Design a priority-lane system for token quota where interactive users are never starved by batch processing jobs.
11. An engineer proposes semantic caching to cut costs by 40%. Under what conditions would you approve this, and what guardrails would you require?
