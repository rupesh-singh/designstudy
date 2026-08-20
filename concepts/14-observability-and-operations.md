# 14. Observability & Operations

Running a distributed system in production requires the ability to understand its internal state from external outputs, to detect and respond to problems quickly, and to evolve it safely. This section covers the instrumentation, alerting, deployment, and operational practices that keep systems reliable.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Monitoring vs observability | Known-unknowns vs unknown-unknowns | Choosing instrumentation strategy |
| Metrics, logs, traces | Three complementary telemetry types | Building observability stack |
| Metric types | Counter, gauge, histogram, summary | Instrumenting services |
| Cardinality explosion | Metrics with too many label combinations | Diagnosing monitoring cost |
| Structured logging | Machine-parseable log entries | Building queryable log infrastructure |
| Distributed tracing | Request flow across services | Debugging latency and failures in microservices |
| RED method | Rate, errors, duration for request-driven services | Monitoring user-facing services |
| USE method | Utilization, saturation, errors for resources | Monitoring infrastructure components |
| Four golden signals | Latency, traffic, errors, saturation | Google's canonical monitoring framework |
| SLI/SLO/SLA/Error budgets | Quantified reliability targets and policies | Balancing reliability vs velocity |
| Alerting best practices | Symptom-based, actionable alerts | Designing on-call alerting |
| Deployment strategies | Safe rollout techniques | Releasing changes to production |
| Rollback vs roll-forward | Recovery direction after failed deploy | Incident response for bad releases |
| Schema migration safety | Non-breaking database changes | Evolving schemas under continuous delivery |
| Configuration management | Dynamic config and its risks | Managing runtime behaviour changes |
| Capacity management | Forecasting and provisioning | Preventing capacity-related outages |
| Incident management | Response structure and learning | Operating under failure |
| DORA metrics | Delivery performance measurement | Assessing engineering effectiveness |
| Data quality monitoring | Pipeline freshness/completeness | Operating data-intensive systems |

## Telemetry Foundations

### Monitoring vs Observability
**What.** Monitoring checks pre-defined conditions (known-unknowns: "is CPU above 90%?"). Observability is the property that lets you ask arbitrary questions about system state from its outputs — enabling investigation of unknown-unknowns you didn't anticipate.
**Use when.** Monitoring suffices for well-understood systems. Observability is essential when failures are emergent and unpredictable (distributed systems, complex interactions).
**Advantages.**
- Monitoring: simple, cheap, well-established tooling
- Observability: enables debugging novel failure modes without deploying new instrumentation
**Tradeoffs.**
- Observability requires richer telemetry (high-cardinality data, traces), which costs more to store and query
- Pure monitoring misses failures you didn't predict
**Staff signal.** A system is observable when an engineer can determine why it's broken from telemetry alone, without needing to add more logging and redeploy. The test is: "Can I answer a question I've never asked before?"

### The Three Pillars: Metrics, Logs, Traces
**What.** Metrics are numeric time series (cheap, aggregated, good for alerting). Logs are discrete textual events (rich context, expensive at volume). Traces are request-scoped DAGs of spans across services (show causality and latency breakdown).
**Use when.** Every production system needs all three; the balance shifts by use case.
**Advantages.**
- Metrics: low cost per signal, excellent for dashboards and alerts; O(1) storage per time series
- Logs: full context for debugging specific incidents
- Traces: reveal inter-service dependencies and latency attribution
**Tradeoffs.**
- Logs at scale are extremely expensive (terabytes/day); require aggressive sampling or tiering
- Traces require propagation headers and instrumentation in every service
- Metrics lose detail (you can't reconstruct individual requests from aggregates)
**Staff signal.** The cost profile matters: metrics cost ~$0.01/series/month, logs ~$0.50/GB ingested, traces proportional to sampled request volume. Design your instrumentation budget accordingly.

### Metric Types: Counter, Gauge, Histogram, Summary
**What.** Counter: monotonically increasing value (requests served). Gauge: point-in-time value (queue depth). Histogram: buckets that capture value distribution (request latency). Summary: client-side quantile calculation.
**Use when.** Counter for rates (derive with rate()), gauge for current state, histogram for latency/size distributions.
**Advantages.**
- Histograms are aggregatable across instances (bucket counts can be summed)
- Counters survive process restarts (rate function handles resets)
**Tradeoffs.**
- Summaries calculate quantiles on the client — these cannot be aggregated across hosts (you cannot average percentiles and get a valid percentile)
- Histograms require choosing bucket boundaries upfront; poor choices lose precision
**Staff signal.** Never average p99s from multiple hosts — the result is mathematically meaningless. Use histograms with Prometheus-style bucket merging, or use a sketch (t-digest) that supports merging. This is one of the most common observability errors at senior+ level.

### Cardinality Explosion
**What.** When metric labels have unbounded or very high distinct values (user IDs, request paths with parameters), the number of time series grows explosively, overwhelming the storage backend.
**Use when.** Designing metric labels; diagnosing why Prometheus/Datadog costs spike.
**Advantages.**
- High-cardinality labels give fine-grained insight when cardinality is bounded and intentional
**Tradeoffs.**
- Each unique label combination creates a new time series; millions of series degrade query performance and increase cost by orders of magnitude
- Prometheus' TSDB performance degrades sharply above ~10M active series
**Staff signal.** Before adding a label, ask: "What is the upper bound of distinct values?" If unbounded (user IDs, trace IDs), that datum belongs in logs or traces, not metrics.

### Structured Logging
**What.** Log entries emitted as key-value or JSON records rather than free-form text, enabling machine parsing, filtering, and aggregation.
**Use when.** Any system where logs are queried programmatically (which should be all of them in production).
**Advantages.**
- Enables fast filtering (e.g., `service=payments AND status=500 AND user_id=X`)
- Consistent schema makes cross-service correlation possible
**Tradeoffs.**
- More verbose on disk; slight overhead in serialization
- Requires discipline: teams must follow schema conventions
**Staff signal.** Sampling is essential at scale — logging every request at 100K RPS produces ~8 GB/hour of raw logs. Use head-based sampling (log 1-in-N) for steady-state, but always log errors unsampled. Be vigilant about PII in logs — structured logging makes accidental PII exposure easier to audit but also easier to accidentally include.

### Distributed Tracing
**What.** Propagating a trace context (trace ID + span ID) through every service call so that the full request journey can be reconstructed as a tree of spans with timing information.
**Use when.** Debugging latency in multi-service request paths; understanding dependencies; identifying bottleneck services.
**Advantages.**
- Pinpoints exactly which service/call contributed latency
- Shows parallel vs sequential call patterns
**Tradeoffs.**
- Requires header propagation through every hop (broken if any middleware strips headers)
- Storage cost proportional to sampled traces × span count; can be very expensive at high throughput
**Staff signal.** Head-based sampling (decide at ingress whether to sample) is simple but misses rare errors. Tail-based sampling (decide after the request completes, keeping interesting ones) captures all errors and slow requests but requires buffering all spans temporarily. Tail-based is architecturally more complex but far more useful for debugging.

## Monitoring Frameworks

### RED Method
**What.** For request-driven services, monitor: Rate (requests/sec), Errors (failed requests/sec), Duration (latency distribution).
**Use when.** Monitoring any service that serves requests (APIs, web servers).
**Advantages.**
- Directly reflects user experience
- Simple — three signals per service give a strong health picture
**Tradeoffs.**
- Doesn't cover resource-level problems (disk filling, connection pool exhaustion)
**Staff signal.** RED is the right framework for services; USE (below) is the right framework for resources. Confusing the two leads to gaps in coverage.

### USE Method
**What.** For every resource (CPU, memory, disk, network, locks): measure Utilization (% busy), Saturation (queue depth / backlog), Errors (error events).
**Use when.** Monitoring infrastructure components and identifying hardware-level bottlenecks.
**Advantages.**
- Systematically covers all physical and logical resources
- Saturation is a leading indicator (problems before failures)
**Tradeoffs.**
- Doesn't directly measure user impact; needs pairing with RED for user-facing signals
**Staff signal.** Utilization at 100% is not always bad (CPU-bound batch jobs) — it's saturation that indicates a problem (requests queuing). Always check saturation alongside utilization.

### Four Golden Signals
**What.** Google's SRE canonical signals: latency, traffic, errors, saturation. Essentially a unification of RED + key resource signals.
**Use when.** As a baseline monitoring checklist for any service.
**Advantages.**
- Covers both user-facing and resource-level signals in one framework
**Tradeoffs.**
- Generic — may need service-specific signals beyond these four
**Staff signal.** Latency should be measured separately for successful vs failed requests. Errors that fail fast (return 500 in 2 ms) skew the overall latency distribution downward, hiding real performance problems on the success path.

## Reliability Engineering

### SLI, SLO, SLA, Error Budgets
**What.** SLI: a quantitative measure of service behaviour (e.g., proportion of requests < 300 ms). SLO: target value for an SLI (e.g., 99.9% of requests < 300 ms per 30-day window). SLA: contractual commitment with consequences for breach. Error budget: the allowed unreliability (100% − SLO) which teams can "spend" on risky changes.
**Use when.** Defining reliability targets; negotiating feature velocity vs stability.
**Advantages.**
- Makes reliability discussions objective and data-driven
- Error budgets align incentives: when budget is spent, freeze risky changes; when budget is ample, ship faster
**Tradeoffs.**
- Poorly chosen SLIs (e.g., uptime of a process rather than success of user operations) lead to false confidence
- Error budgets require cultural buy-in; without enforcement they are theatre
**Staff signal.** The error budget policy is the real tool: "If budget is exhausted, the team halts feature work and focuses on reliability." Without this policy, SLOs are aspirational. The staff-level insight is that SLOs should be set just tight enough — too tight and you can never ship; too loose and users suffer.

### Alerting: Symptoms vs Causes; Burn-Rate Alerts
**What.** Alert on symptoms (user-visible impact: elevated error rate, high latency) rather than causes (high CPU, disk at 80%). Burn-rate alerts fire when the error budget is being consumed faster than a sustainable rate, using multi-window comparison (e.g., 1h burn rate > 14x AND 5m burn rate > 14x).
**Use when.** Designing on-call alerting; reducing alert fatigue.
**Advantages.**
- Symptom-based alerts are actionable (something is broken for users now)
- Burn-rate alerts avoid both alert fatigue (too sensitive) and late detection (too slow)
**Tradeoffs.**
- Cause-based alerts are still useful as diagnostic aids (but should not page)
- Multi-window burn-rate logic is complex to configure correctly
**Staff signal.** Every alert must have: (1) a clear meaning, (2) an action the on-call can take, (3) priority that matches actual user impact. If an alert fires and the on-call's only response is "acknowledge and ignore," the alert should be deleted.

## Deployment & Release

### Deployment Strategies
**What.** Rolling: gradually replace instances. Blue-green: spin up complete new environment, switch traffic atomically. Canary: route small percentage to new version, monitor, then promote. Feature flags: deploy code dark, enable for subsets. Progressive delivery: automated canary promotion based on metric analysis.
**Use when.** Any production release — choose strategy based on blast radius tolerance and rollback speed needed.
**Advantages.**
- Canary catches regressions with limited blast radius (~1-5% of traffic)
- Blue-green enables instant rollback (switch back to blue)
- Feature flags decouple deployment from release
**Tradeoffs.**
- Blue-green: doubles infrastructure cost during deployment window
- Canary: requires good automated analysis; manual observation doesn't scale
- Feature flags: stale flags accumulate as tech debt; complex flag interactions can cause combinatorial bugs
**Staff signal.** Automated canary analysis (comparing error rates, latency percentiles between canary and baseline) is what makes canary deployments practical at scale. Without automation, teams either skip canary waits (defeating the purpose) or delay releases for manual observation.

### Rollback vs Roll-Forward
**What.** Rollback: revert to the previous version. Roll-forward: fix the issue with a new deployment. Database migrations constrain rollback — if a migration dropped a column, you cannot simply redeploy old code.
**Use when.** Deciding how to recover from a bad deployment.
**Advantages.**
- Rollback: fastest recovery if the binary is known-good and data is compatible
- Roll-forward: necessary when rollback is impossible due to irreversible changes
**Tradeoffs.**
- Rollback requires that the previous version is still compatible with the current database schema
- Roll-forward under incident pressure is risky; having a pre-prepared fix is better
**Staff signal.** Design database migrations to be backward-compatible for at least one release cycle. This means: no column drops, no renames — use expand-contract. If every migration is backward-compatible, rollback is always safe.

### Schema Migration Safety
**What.** Techniques for changing database schemas without downtime: expand-contract (add new → migrate data → remove old), online schema change tools (gh-ost, pt-online-schema-change for MySQL; zero-downtime on PostgreSQL via CREATE INDEX CONCURRENTLY), backfill throttling (rate-limited data migration to avoid overwhelming the database).
**Use when.** Any schema change in a system with zero-downtime requirements.
**Advantages.**
- Expand-contract guarantees rollback safety at every step
- Online DDL tools avoid table locks that block writes
**Tradeoffs.**
- Multi-step migrations are slow (days for large tables) and require coordination
- Backfill throttling extends migration duration; must be balanced against consistency window
**Staff signal.** The most dangerous schema migration is one that looks safe but isn't: adding a NOT NULL column without a default on a large table, or creating an index without CONCURRENTLY, can lock writes for hours on PostgreSQL.

## Operational Practices

### Configuration Management and Dynamic Config
**What.** Externalising runtime behaviour into configuration that can be changed without redeployment. Dynamic config (feature flags, circuit breaker thresholds) changes take effect without restarts.
**Use when.** Any system where behaviour must adapt faster than deploy cycles allow.
**Advantages.**
- Enables rapid response (disable a broken feature in seconds)
- Decouples config change from code change and deploy pipeline
**Tradeoffs.**
- Config changes are a leading cause of outages (mistyped value, incompatible combination)
- Requires the same rigour as code: version control, review, staged rollout, rollback
**Staff signal.** Treat config changes as production changes. The majority of major outages at large companies stem from configuration errors, not code bugs. Apply canary, validation, and rollback to config the same way you do to code.

### Incident Management
**What.** Structured response to service-impacting events: detection, triage, mitigation, resolution, communication, and learning. Includes severity levels, incident commander role, and blameless postmortems.
**Use when.** Any unplanned service degradation.
**Advantages.**
- Structured response reduces MTTR; clear roles prevent duplication of effort
- Blameless postmortems enable learning without fear
**Tradeoffs.**
- Process overhead for minor incidents; calibrating severity thresholds is hard
- "Blameless" degrades if leadership doesn't truly enforce it
**Staff signal.** "Root cause" is often a misnomer — complex system failures have contributing factors, not a single root cause. The "five whys" technique is useful as a starting point but fails for systemic issues (it converges on a single causal chain when reality is multi-causal). Good postmortems identify multiple contributing factors and systemic patterns.

### DORA Metrics
**What.** Four metrics measuring software delivery performance: deployment frequency, lead time for changes, change failure rate, MTTR (mean time to restore). Elite performers deploy multiple times daily with < 1 hour lead time and < 15% failure rate.
**Use when.** Assessing and improving engineering team effectiveness; justifying platform investments.
**Advantages.**
- Empirically validated correlation with organisational performance
- Balances velocity (frequency, lead time) with stability (failure rate, MTTR)
**Tradeoffs.**
- Goodhart's Law: optimizing metrics directly can produce gaming (tiny meaningless deploys to boost frequency)
- Must be interpreted in context, not used as targets
**Staff signal.** DORA metrics improve together — high deployment frequency with robust CI/CD and observability actually reduces failure rate (smaller changes are safer). Teams that sacrifice stability for speed have not achieved high performance; they've shifted the cost to operations.

### Capacity Management and Load Forecasting
**What.** Projecting future resource needs from growth trends, seasonality, and planned launches; provisioning ahead of demand.
**Use when.** Preventing capacity-related outages; budgeting infrastructure spend.
**Advantages.**
- Proactive provisioning avoids scale-up lag during traffic surges
**Tradeoffs.**
- Over-provisioning wastes money; under-provisioning causes outages
- Forecasting is inaccurate for viral growth or novel events
**Staff signal.** Combine organic growth forecasting with headroom multipliers (e.g., 2× peak for critical services). For planned events (product launches, sales), load test at expected peak and provision accordingly — do not trust autoscaling alone for step-function traffic increases.

### Toil and Automation
**What.** Toil is repetitive, manual operational work that scales linearly with service size and produces no lasting value. Automation eliminates toil by codifying operational procedures.
**Use when.** Operational maturity assessments; prioritising platform engineering work.
**Advantages.**
- Reducing toil frees engineering time for high-value work
- Automation is more reliable and faster than manual steps
**Tradeoffs.**
- Automating rare events may cost more than occasionally doing them manually
- Brittle automation that fails silently is worse than manual processes with checklists
**Staff signal.** The decision framework: automate if the task recurs frequently, is error-prone manually, or must complete quickly (incident response). Don't automate one-off tasks unless they'll become recurring.

### Data Quality Monitoring
**What.** Monitoring data pipelines for freshness (data arrives on time), completeness (no missing records), and correctness (values within expected ranges). Treat data quality as an SLO.
**Use when.** Operating ETL/ELT pipelines, ML feature stores, or any system where downstream decisions depend on data quality.
**Advantages.**
- Catches pipeline failures before they impact downstream consumers or business decisions
**Tradeoffs.**
- Defining "correct" is domain-specific and requires business context
- Monitoring adds latency to pipeline completion (validation step)
**Staff signal.** Freshness SLOs should propagate: if Dashboard X needs data within 1 hour, and the pipeline has three stages, each stage must have a tighter freshness target. Budget slack time for retries.

## Common interview traps

- Confusing SLO with SLA — SLO is an internal engineering target; SLA is a contractual commitment with financial consequences.
- Averaging percentiles across instances and presenting the result as a valid percentile — it's statistically meaningless.
- Proposing blue-green deployment without addressing database schema compatibility between the two versions.
- Describing canary deployment without automated metric comparison — manual observation does not scale and is unreliable.
- Setting alerts on causes (CPU > 80%) instead of symptoms (error rate elevated) — the former creates alert fatigue without actionability.
- Ignoring the cost of observability itself (log storage, trace sampling, metric cardinality) as if telemetry is free.
- Treating "five whys" as sufficient for complex incident analysis — it assumes single linear causation.
- Forgetting that feature flags are a form of config and require cleanup; stale flags compound complexity.
- Proposing rollback without considering whether recent database migrations are backward-compatible.
- Monitoring utilization alone without checking saturation — a system at 70% CPU with deep request queues is already in trouble.

## Drill questions

1. Your p99 latency alert fires but individual host dashboards all show healthy p99. What's happening and how do you fix the observability gap?
2. Design an error budget policy for a service with a 99.95% availability SLO. What happens when the budget is exhausted?
3. You need to add a column to a 500M-row PostgreSQL table used by a service doing 5K writes/sec. Walk through the safe migration sequence.
4. A canary deployment shows 0.5% error rate vs 0.3% baseline. Is this significant? What determines your promote/rollback decision?
5. Your tracing system samples at 1%. A rare but critical error occurs in 0.01% of requests. How do you ensure it's captured?
6. A config change caused a global outage. Design a config deployment system that prevents this class of failure.
7. You're debating whether to alert on queue depth or consumer lag. Which is the better SLI for a message processing service, and why?
8. After an incident, the postmortem identifies "human error" as the root cause. Why is this insufficient and what should the postmortem actually conclude?
9. Your log pipeline costs $50K/month. What strategies reduce cost without losing debugging ability?
10. Explain why monitoring a batch pipeline requires different signals than a request-serving system. What are the right SLIs?
11. A team's deployment frequency is high but MTTR is also high. What does this pattern suggest, and what would you investigate?
