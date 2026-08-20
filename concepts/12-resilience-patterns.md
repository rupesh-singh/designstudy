# 12. Resilience, Flow Control & Failure Handling

Distributed systems fail constantly — networks partition, processes crash, disks fill, dependencies slow down. Resilience engineering is not about preventing failures but about constraining their blast radius, maintaining degraded operation, and recovering without human intervention. The patterns here convert unpredictable partial failures into predictable, bounded degradation.

## Quick reference

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Timeout | Bound the wait time for any remote call | Every network call (no exceptions) |
| Retry with backoff | Recover from transient faults | Idempotent operations against flaky dependencies |
| Circuit breaker | Stop calling a known-failing dependency | Repeated failures that won't resolve by retrying |
| Bulkhead | Isolate failure to a compartment | Preventing one slow dependency from consuming all threads |
| Rate limiting | Cap inbound request rate | Protecting services from overload or abuse |
| Load shedding | Reject excess work proactively | Preserving quality for admitted requests |
| Backpressure | Signal upstream to slow down | Bounded queues, streaming pipelines |
| Hedged requests | Race redundant requests for latency | Tail-latency reduction where capacity allows |
| Graceful degradation | Serve reduced functionality vs total failure | Non-critical features backed by failing dependencies |
| Circuit breaker | Fast-fail when dependency is down | Avoid wasting resources on hopeless calls |
| Cell architecture | Hard isolation between customer cohorts | Limiting correlated failure radius |
| Shuffle sharding | Combinatorial isolation across shared infrastructure | Multi-tenant systems needing blast-radius reduction |

## Failure Fundamentals

### Failure Domains and Blast Radius
**What.** A failure domain is the set of components that share a single point of failure: a rack (shared power/switch), an availability zone (shared data centre), a region (shared control plane), or a dependency (shared library, config). Blast radius is how much of the system is affected when that domain fails.
**Use when.** Every architecture review — explicitly identify failure domains and draw boundaries that contain them.
**Advantages.**
- Thinking in failure domains forces explicit decisions about which failures you tolerate vs mitigate
**Tradeoffs.**
- Reducing blast radius requires redundancy across domains, which increases cost and operational complexity
**Staff signal.** Correlated failure is the real danger: deploying all replicas to the same AZ, using one config push to update every instance simultaneously, or depending on a single DNS provider. Staff engineers design for independent failure by placing replicas across uncorrelated domains.

### Redundancy Models
**What.** N+1: one spare beyond minimum needed. Active-active: all replicas serve traffic simultaneously. Active-passive: standby takes over on primary failure. Hot standby: replica is running and nearly current. Warm standby: replica exists but needs catch-up. Cold standby: resources provisioned but not running.
**Use when.** Choose based on RTO (recovery time objective): hot gives seconds, warm gives minutes, cold gives hours.
**Advantages.**
- Active-active uses all capacity all the time (no idle waste) and provides instant failover
**Tradeoffs.**
- Active-active requires solving data consistency across replicas (conflict resolution, quorum writes)
- Hot standby wastes resources during normal operation
**Staff signal.** Active-active across regions sounds ideal but demands either eventual consistency or cross-region consensus (high latency). Most systems that claim "active-active" actually have one authoritative region per data partition — it's active-active for compute but active-passive for data ownership.

## Timeout & Retry

### Timeouts
**What.** A deadline after which a caller gives up waiting for a response and treats the call as failed. Must be set for every network call — connect timeout (short, ~1–5 s) and request timeout (derived from the dependency's p99 latency plus margin).
**Use when.** Every outbound call. No exceptions. An absent timeout means unbounded resource consumption.
**Advantages.**
- Prevents thread/connection exhaustion from slow or hung dependencies
- Makes failure explicit and handleable rather than silent
**Tradeoffs.**
- Too-short timeouts cause spurious failures under normal tail latency; too-long timeouts defeat the purpose
- Timeout chosen from average latency will fire on ~50 % of requests during load spikes
**Staff signal.** Set timeouts from percentile data: p99 + buffer for critical paths, p95 for non-critical. Never guess. Propagate deadline context (like gRPC deadlines) across call chains so downstream services know how much time remains and can skip work if the budget is exhausted.

### Retries, Backoff, and Retry Amplification
**What.** Retrying a failed request after a delay. Exponential backoff: delay doubles each attempt (1 s, 2 s, 4 s, …). Jitter variants: full jitter (random in [0, backoff]), equal jitter (backoff/2 + random in [0, backoff/2]), decorrelated jitter (random in [base, last_delay × 3]). Retry budget: a service allows only X % of its total calls to be retries (e.g., 10 %) — once exceeded, further retries are suppressed.
**Use when.** Transient failures (network blip, brief overload) against idempotent operations.
**Advantages.**
- Recovers from transient failures automatically without human intervention
- Backoff with jitter spreads retry load over time, preventing synchronised retry storms
**Tradeoffs.**
- Naive retries amplify load: in a three-tier chain (A → B → C), if each tier retries 3×, a single failure at C can generate 3 × 3 = 9 attempts at C, and 3 × 3 × 3 = 27 at the originator's budget. This multiplicative amplification can convert a minor failure into cascading overload.
- Retries increase end-to-end latency (caller waits through backoff delays)
**Staff signal.** Retry amplification in deep call graphs is a staff-level concept. Mitigation: (1) retry only at the outermost layer (the edge); intermediate services propagate errors rather than retrying; (2) use retry budgets (token-bucket per service: spend one token per retry, earn them back over time); (3) propagate deadlines — don't retry if the deadline has already passed.

### Idempotency as Retry Precondition
**What.** An operation is idempotent if executing it multiple times produces the same result as executing it once. Retrying non-idempotent operations (e.g., charging a credit card) without idempotency keys causes duplication.
**Use when.** Any system that retries mutations must first ensure those mutations are idempotent — either naturally (PUT, DELETE) or explicitly (via idempotency keys).
**Advantages.**
- Makes the entire retry/timeout/circuit-breaker stack safe to use for mutations
**Tradeoffs.**
- Achieving idempotency requires server-side deduplication state (storing processed keys) with appropriate TTL
**Staff signal.** Idempotency is not just an API nicety — it is the precondition that unlocks safe retries, safe hedging, and safe exactly-once delivery in distributed systems. Without it, every retry mechanism is dangerous for writes.

## Circuit Breaking & Isolation

### Circuit Breaker
**What.** Tracks failure rate to a dependency. In closed state, requests flow normally. When failures exceed a threshold, it opens: all requests fail immediately (fast-fail) without calling the dependency. After a cooldown, it transitions to half-open: a limited number of probes test recovery. If probes succeed, it closes; if they fail, it re-opens.
**Use when.** Protecting your service from wasting resources calling a dependency that is known to be down, and protecting that dependency from retry storms during recovery.
**Advantages.**
- Fast-fail preserves threads and connections for other work
- Gives the failing dependency time to recover without additional pressure
**Tradeoffs.**
- During the open state, you must have a fallback strategy (cached response, degraded feature, error)
- Tuning thresholds is hard: too sensitive causes unnecessary fast-fail; too tolerant delays protection
**Staff signal.** Circuit breakers per-endpoint (not per-host) are more precise. Also, in the open state, serving a stale cached response (graceful degradation) is almost always preferable to serving an error.

### Bulkhead Isolation
**What.** Partitioning resources (thread pools, connection pools, process boundaries) so that failure or saturation in one partition cannot consume resources needed by others. Named after ship compartments that contain flooding.
**Use when.** A service calls multiple dependencies with different reliability profiles; you want a slow dependency to not block unrelated fast paths.
**Advantages.**
- One degraded dependency saturates only its allocated pool, leaving others unaffected
- Cell-based architecture is bulkheading at infrastructure scale: customers are isolated into independent cells
**Tradeoffs.**
- Requires allocating resources per partition — total capacity appears lower in steady state (resource waste during normal operation)
- Sizing each bulkhead requires understanding per-dependency concurrency needs
**Staff signal.** Bulkheading at the infrastructure level (cell-based architecture) isolates not just threads but databases, queues, and caches per cell. A failure in Cell A — even a data-corruption bug — doesn't touch Cell B.

## Rate Limiting & Admission Control

### Rate Limiting Algorithms
**What.** Fixed window: count requests per time window (e.g., 100/minute); resets at window boundary. Sliding window log: store timestamp of each request, count within last N seconds (precise but memory-heavy). Sliding window counter: interpolate between current and previous window counts (approximate, low memory). Token bucket: bucket holds up to B tokens, refills at rate R/sec; each request costs one token; allows bursts up to B. Leaky bucket: requests enter a queue drained at fixed rate; excess is rejected; smooths output perfectly.
**Use when.** Protecting services from overload, enforcing usage quotas, preventing abuse.
**Advantages.**
- Token bucket allows controlled bursts while maintaining average rate — matches real traffic patterns well
- Sliding window counter is the best accuracy-to-memory ratio for most use cases
**Tradeoffs.**
- Fixed window has boundary burst: 100 requests at :59 and 100 at :00 = 200 in 2 seconds despite 100/min limit
- Sliding log stores every timestamp: O(N) memory per user for N requests in the window
**Staff signal.** In an interview, explain the fixed-window boundary burst explicitly and show how sliding window counter mitigates it with only two counters per window (previous count × overlap fraction + current count).

### Distributed Rate Limiting
**What.** Enforcing a global rate limit across multiple service instances. Options: centralised counter (Redis INCR with TTL), synchronised local counters (periodic gossip/sync), or local-only approximation (each instance enforces limit/N).
**Use when.** Any multi-instance service with per-user or global rate limits.
**Advantages.**
- Centralised (Redis) gives exact global counts
- Local approximation has zero coordination latency
**Tradeoffs.**
- Centralised adds a Redis dependency on the hot path — if Redis is slow, every request is slow
- Local approximation under-counts when traffic distribution across instances is uneven (one instance may admit all traffic)
**Staff signal.** The practical hybrid: local token buckets handle the fast path; periodically synchronise with a centralised store to reconcile. Accept brief over-admission during sync gaps rather than adding Redis latency to every request.

### Load Shedding and Admission Control
**What.** When a service is at capacity, proactively reject excess requests rather than attempting to serve them all poorly. Prioritised shedding drops low-value traffic first (e.g., background syncs before user-facing reads).
**Use when.** A service is approaching its throughput ceiling and you want to preserve quality for admitted traffic.
**Advantages.**
- Prevents latency degradation for all users by sacrificing a fraction; maintains SLO for high-priority requests
- Shedding is cheaper than serving: a rejected request consumes nearly zero server resources
**Tradeoffs.**
- Requires classifying traffic by priority — which is a product/business decision, not just a technical one
- Clients must handle rejections gracefully (retry with backoff, degrade UI)
**Staff signal.** CoDel-inspired admission control: measure queue wait time; if requests wait longer than a threshold, begin shedding. This is superior to counting concurrent requests because it directly measures the user-experienced symptom (latency) rather than a proxy (concurrency).

## Backpressure & Queue Management

### Backpressure and Bounded Queues
**What.** Backpressure is a mechanism by which a downstream consumer signals to upstream producers that it cannot keep up, causing producers to slow down or shed. Bounded queues are the enforcement mechanism: when the queue is full, producers must block, drop, or receive an error.
**Use when.** Any pipeline or streaming system. Unbounded queues should be treated as bugs.
**Advantages.**
- Prevents memory exhaustion (unbounded queues grow until OOM)
- Makes overload visible immediately rather than hiding it behind growing latency
**Tradeoffs.**
- Backpressure propagation through a chain increases upstream latency — acceptable for correctness, but must be planned for
- If every stage exerts backpressure, the system's throughput is limited by its slowest stage
**Staff signal.** An unbounded queue is a latency bug: it converts a throughput problem (too many requests) into a latency problem (requests wait indefinitely). Worse, work in the queue may have already timed out at the caller, so the server processes dead work — the "queue full of timed-out requests" failure mode.

### Queue Depth as Leading Indicator
**What.** Rising queue depth (before latency spikes) is the earliest signal that a system is approaching saturation. If items in the queue are older than the caller's timeout, the server is doing wasted work.
**Use when.** Monitoring and alerting for capacity planning; as a trigger for auto-scaling or shedding.
**Advantages.**
- Alerts on queue growth give minutes of warning before user-visible latency degradation
**Tradeoffs.**
- Requires instrumenting all internal queues (not just inter-service queues)
**Staff signal.** The "dead letter in the fast lane" problem: a server dequeues a message that was enqueued 30 seconds ago, processes it for 200 ms, and returns a result — but the client timed out at 5 seconds. The server has wasted 200 ms of its capacity on work whose result will be discarded. Solution: check request age against deadline before processing; discard if over budget.

## Advanced Resilience Patterns

### Hedged Requests and Tied Requests
**What.** Hedged request: after waiting for the p50 latency with no response, send a duplicate request to a different backend; use whichever responds first and cancel the other. Tied request: send to two backends simultaneously, but the second backend only begins work if the first hasn't finished within a threshold.
**Use when.** Tail-latency-sensitive systems where occasional slow responses matter (e.g., Google search fanout to many shards).
**Advantages.**
- Dramatically reduces tail latency (p99 drops to approximately p99² of a single backend if uncorrelated)
- Tied requests avoid doubling load because the second backend defers until needed
**Tradeoffs.**
- Hedging costs additional capacity: in the naive case (immediate duplication), throughput demand doubles
- Only effective if latency variability is high and backends are uncorrelated
**Staff signal.** Google's "The Tail at Scale" paper shows that hedging after the p95 adds only ~5 % extra load while dramatically cutting tail latency. The key insight: you're spending a small amount of extra capacity to eliminate the long tail, not doubling load.

### Graceful Degradation
**What.** Serving reduced-quality or partial results when a dependency is unavailable, rather than failing entirely. Examples: returning cached (stale) recommendations when the recommendation service is down; showing a generic avatar when the image service fails.
**Use when.** Any feature backed by a non-critical dependency. Classify dependencies as critical (user cannot proceed without it) vs non-critical (degrade gracefully).
**Advantages.**
- Users experience slightly worse functionality rather than error pages
- Keeps the core user journey operational even during partial outages
**Tradeoffs.**
- Requires pre-computing fallback responses and testing degraded paths (which are rarely exercised and thus rot)
- Risk of degraded mode becoming the permanent state without alerts
**Staff signal.** Classify every dependency call in your service as critical or non-critical. Non-critical calls should have a circuit breaker and a fallback. Critical calls should have retries and aggressive timeouts — but no fake fallback (it's better to show an error than to silently return wrong data for a critical dependency).

### Metastable Failures / Congestion Collapse
**What.** A system enters a state where it remains degraded even after the triggering overload subsides, because the system's own recovery mechanisms (retries, queue drainage, cache rebuilding) sustain the overload. The feedback loop: overload → timeouts → retries → more load → more overload.
**Use when.** Understanding why systems sometimes don't recover after a load spike drops — one of the strongest staff/principal-level topics.
**Advantages.**
- Recognising metastability lets you design circuit-breakers and backoff that break the feedback loop
**Tradeoffs.**
- Solutions often require deliberate shedding or pausing of recovery mechanisms — counterintuitive under pressure
**Staff signal.** The canonical example: cache failure causes all traffic to hit the database; the database becomes slow; clients timeout and retry; retries double the database load; slowness increases; more retries. The system is stable only in two states: healthy (cache absorbs load) or collapsed (everything retrying). Recovery requires breaking the loop: stop retries (circuit break), reject new traffic (shed), warm the cache (restore the absorber), then gradually re-admit traffic. Metastability explains why "just wait for load to drop" doesn't work — the sustained retry storm *is* the load.

### Cell-Based Architecture and Shuffle Sharding
**What.** Cell architecture: partition infrastructure into independent cells, each serving a subset of customers. A failure (even a catastrophic bug) in one cell affects only that cell's customers. Shuffle sharding: instead of assigning each customer to one cell, assign each customer to a unique *combination* of resources from a shared pool. With N resources and cells of size K, there are C(N, K) possible assignments.
**Use when.** Multi-tenant systems where total isolation is too expensive but strong blast-radius containment is required.
**Advantages.**
- Cell architecture: hard failure boundary — a memory leak, bad deploy, or data corruption stays within one cell
- Shuffle sharding: with 8 shards and cells of 2, there are C(8,2) = 28 possible cells. Two customers share a cell only if they were assigned the exact same combination. A "poisonous" customer affects only their specific combination — no other customer sees both affected shards.
**Tradeoffs.**
- Cell architecture requires duplicating stateless and often stateful infrastructure per cell; higher cost
- Shuffle sharding provides probabilistic (not absolute) isolation — but the combinatorics make overlap very unlikely with sufficient pool size
**Staff signal.** Explain the combinatorial benefit precisely: with N=100 workers in groups of K=5, there are C(100,5) ≈ 75 million possible assignments. The probability that two customers share all 5 workers is astronomically small. AWS uses this in Route 53 and other services to isolate tenants without per-tenant infrastructure.

### Thundering Herd on Recovery
**What.** When a failed service comes back online, all waiting clients simultaneously retry, producing an immediate overload spike that may re-crash the service.
**Use when.** Any service recovering from failure that has accumulated queued or retrying clients.
**Advantages.**
- Awareness enables preventive measures (jittered restarts, gradual ramp-up)
**Tradeoffs.**
- Mitigation requires coordination between the recovering service and its clients
**Staff signal.** Combine: (1) exponential backoff with jitter on client retries, (2) admission control on the recovering service (start by accepting a fraction of traffic and ramp up), (3) a load balancer that gradually adds the backend to the pool rather than immediately directing 100 % of traffic to it.

## Disaster Recovery

### RPO, RTO, and Backup Strategy
**What.** Recovery Point Objective (RPO): maximum acceptable data loss measured in time (e.g., RPO=1 hour means losing up to 1 hour of data is tolerable). Recovery Time Objective (RTO): maximum time to restore service after failure. Backup strategies: full, incremental, differential; plus continuous replication for near-zero RPO.
**Use when.** Every system design must declare its RPO and RTO requirements — they drive architecture choices.
**Advantages.**
- Explicit RPO/RTO requirements clarify which replication and backup mechanisms are needed
**Tradeoffs.**
- Near-zero RPO/RTO requires synchronous replication and hot standby — highest cost
- Backups that are never restore-tested are not backups; they are hopes
**Staff signal.** "We do nightly backups" is not a DR strategy unless you've tested restore and measured that the RTO meets requirements. The number-one disaster recovery failure mode: the backup exists but cannot be restored (corrupted, incompatible schema version, missing encryption key).

### Multi-Region Architecture
**What.** Deploying across geographic regions for disaster tolerance. Active-passive: one region serves traffic, another is on standby. Active-active: both regions serve traffic, requiring data synchronisation. Split-brain: both sides believe they are primary after a partition — can cause conflicting writes.
**Use when.** RTO requirements demand faster failover than rebuilding in a new region (typically RTO < 15 minutes).
**Advantages.**
- Active-active also provides geographic latency reduction (not just DR)
**Tradeoffs.**
- Active-active data synchronisation is the hardest distributed systems problem: conflict resolution, eventual consistency, and cross-region latency on consensus
- Split-brain avoidance requires fencing mechanisms or quorum-based leader election that spans regions
**Staff signal.** True active-active multi-region for strongly consistent data requires either: (1) accepting eventual consistency with conflict resolution (CRDT, last-writer-wins), or (2) paying the cross-region round-trip on every write (Spanner's approach with TrueTime and synchronous replication). There is no free lunch — pick one.

## Chaos Engineering

### Chaos Engineering and Game Days
**What.** Deliberately injecting failures (network latency, process crashes, AZ outages) into production or staging to validate resilience mechanisms work as designed. Game days are scheduled exercises where teams practice incident response against injected failures.
**Use when.** After building resilience patterns — to verify they actually work under realistic conditions.
**Advantages.**
- Discovers latent failures before they occur naturally in production during critical moments
- Builds team muscle memory for incident response
**Tradeoffs.**
- Production chaos requires blast-radius controls (auto-rollback, canary scope) to prevent customer impact
- Requires organizational maturity — premature chaos engineering without basic resilience causes outages, not learning
**Staff signal.** Chaos engineering is hypothesis-driven: "We hypothesize that if AZ-a fails, traffic will shift to AZ-b within 30 seconds with no user-visible errors." You then inject and verify. If the hypothesis fails, you've found a gap before customers did.

### Failing Open vs Failing Closed
**What.** Failing closed: when a security/validation system is unavailable, deny all requests (safe from a security perspective, but causes availability loss). Failing open: when the system is unavailable, allow requests through (maintains availability but risks bypassing controls).
**Use when.** Every security-related check (auth, rate limiting, fraud detection) must declare its failure mode.
**Advantages.**
- Fail-closed protects against security breaches during outages
- Fail-open preserves revenue and user experience during outages
**Tradeoffs.**
- Fail-closed on a critical-path auth check means an auth service outage = total site outage
- Fail-open on fraud detection means a fraud-service outage = unchecked fraud window
**Staff signal.** The answer is context-dependent: rate limiting should fail-open (an outage of the limiter shouldn't cause a site outage), but authentication should usually fail-closed (serving unauthenticated content is worse than downtime for most applications). Knowing *which* checks should fail in which direction is the staff-level insight.

### Health of Dependencies: Critical vs Non-Critical
**What.** Classifying each dependency as critical (service cannot fulfill its primary function without it) or non-critical (degraded functionality is acceptable). This classification determines timeout aggressiveness, fallback strategy, and circuit-breaker behaviour.
**Use when.** Service design — make this classification explicit for every outbound call.
**Advantages.**
- Non-critical dependencies get circuit breakers and graceful fallbacks; critical ones get retries and aggressive SLOs
- Prevents a non-critical dependency failure from cascading into total service failure
**Tradeoffs.**
- Requires product input on what "degraded but acceptable" means — engineers alone cannot decide this
**Staff signal.** Map every dependency call to one of: (1) critical with retry + fallback-to-error, (2) non-critical with circuit-breaker + fallback-to-cached/default, (3) best-effort with fire-and-forget + timeout. This explicit classification prevents the common failure mode where an optional feature's backend outage takes down the entire page.

## Common interview traps

- Implementing retries without idempotency — a subtle but critical error that doubles payments or creates duplicate records.
- Setting retries at every layer of a deep call chain, not realising the multiplicative amplification (3 × 3 × 3 = 27×).
- Describing a circuit breaker without explaining what happens when it's open (fast-fail alone isn't enough — you need a fallback).
- Using unbounded queues and calling it "buffering" — it's actually hiding latency and risking OOM.
- Confusing rate limiting (cap inbound) with backpressure (signal upstream to slow down); they solve different problems.
- Assuming a system will recover automatically once load drops — ignoring metastable failure modes.
- Proposing active-active multi-region without addressing the write-conflict problem.
- Choosing timeouts by gut feeling rather than from measured latency percentiles.
- Describing chaos engineering as "randomly killing things" without the hypothesis-driven methodology.
- Forgetting to jitter retries and restarts, thereby converting a partial failure into a thundering herd.

## Drill questions

1. Service A calls B calls C. Each retries 3× on failure. C starts returning 50 % errors. How many requests does C receive per original request from A? How do retry budgets fix this?
2. Your circuit breaker opens for a payment service. What do you do with incoming payment requests — fail them, queue them, or serve a fallback? Justify your choice.
3. Explain why an unbounded queue converts a throughput problem into a latency problem, and describe the "dead work" scenario.
4. Your system suffered a cache failure, database overloaded, clients retried, and the system didn't recover even after the cache was restored. Walk through the metastable failure loop and describe three interventions to break it.
5. You have 100 shards and assign each tenant to a random pair (K=2). What is the probability two specific tenants share the exact same pair? How does this compare to simple single-shard assignment?
6. Choose between failing open and failing closed for: (a) fraud detection, (b) feature-flag evaluation, (c) authentication. Justify each.
7. A service's p50 latency is 20 ms and p99 is 800 ms. What timeout would you set? How would hedging after p50 reduce tail latency?
8. Your rate limiter uses a fixed window of 100 req/min. A client sends 100 requests at second :59 and 100 at second :00. What happens? How does a sliding window counter fix it?
9. Describe the difference between load shedding and throttling. When is each appropriate? How do you decide *which* traffic to shed?
10. Active-active multi-region with strongly consistent data: explain why you must either accept eventual consistency or pay cross-region latency on every write. What does Spanner do differently?
