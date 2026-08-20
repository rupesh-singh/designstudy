# 17. The Staff/Principal Interview Playbook

Everything else in this reference is knowledge. This file is *judgment* — how to
deploy that knowledge under interview conditions, and what specifically
distinguishes a Staff/Principal answer from a strong Senior one.

---

## The bar: what actually separates the levels

Interviewers are not scoring your vocabulary. They are scoring decision quality
under ambiguity. The observable differences:

| Dimension | Senior answer | Staff/Principal answer |
|---|---|---|
| Requirements | Accepts the prompt as given | Interrogates the prompt; surfaces the requirement that changes the design |
| Scale | "It needs to scale" | Derives numbers, then shows which number forces which decision |
| Components | Names correct components | Justifies each against a rejected alternative |
| Consistency | "We'll use eventual consistency" | Specifies *which* operations need which guarantee, and why the rest can be weaker |
| Failure | Adds retries and replicas | Names the failure mode, its blast radius, and the detection signal |
| Tradeoffs | Lists pros and cons | Commits to a choice and states the condition under which they'd reverse it |
| Evolution | Designs the end state | Designs the migration path from what exists today |
| Cost | Rarely mentioned | Quantifies unit cost and identifies the dominant cost driver |
| Org | Ignores it | Notes team boundaries, ownership, and operational load |

The single highest-signal habit: **state a decision, its trigger condition, and
its reversal condition.** "I'll start with a single Postgres primary. If write
throughput passes roughly 5k/s sustained or the working set stops fitting in
memory, I'd shard by tenant — I'd rather not pay that operational cost until the
data forces it."

---

## The 45-minute structure

Budget deliberately. Most failures are pacing failures, not knowledge failures.

**1. Requirements and scope — 5–8 min.**
Functional: what must it do? Pick 3–4 core flows and explicitly defer the rest.
Non-functional: scale, latency targets per operation, consistency needs,
availability target, durability, retention, security/compliance, cost ceiling.
Ask about read/write ratio — it drives more decisions than raw volume.

**2. Estimation — 3–5 min.**
DAU → QPS (peak = 2–5× average, and state your multiplier), storage per
item × volume × retention, bandwidth, working-set size. Round aggressively.
The purpose is not accuracy; it is to find the *binding constraint*.

**3. API and data model — 5–7 min.**
Define the handful of endpoints and the core entities with their access
patterns. Access patterns should drive storage choice, not the reverse.

**4. High-level design — 8–10 min.**
Draw the boxes. Client → edge/CDN → LB → service tier → storage, plus async
paths. Keep it simple first; complexity should be pulled in by a requirement.

**5. Deep dive — 10–15 min.**
The interviewer usually picks. If they don't, go where the risk is: the hot
partition, the consistency boundary, the fan-out, the thing that breaks at 10×.

**6. Failure, operations, evolution — 5–8 min.**
Failure modes and detection. What you'd monitor. What breaks at 10× scale.
Migration path. Cost.

Signal you're pacing correctly: you reach the deep dive by the halfway mark.

---

## Estimation kit

Round to powers of ten. Nobody wants precision; they want the constraint.

- **Time:** 100k sec/day ≈ 1e5. 1M/day ≈ 12/s. 1B/day ≈ 12k/s.
- **Peak factor:** 2–5× average for consumer traffic. State your assumption.
- **Storage:** 1M × 1KB = 1GB. 1B × 1KB = 1TB.
- **A rough machine:** ~10–50k simple QPS; 64–256GB RAM; ~1–10 Gbps NIC.
- **Latency ladder (approximate orders of magnitude):** memory ~100ns; SSD random
  read ~100µs; disk seek ~10ms; same-DC round trip ~0.5ms; cross-country
  ~50–70ms; intercontinental ~150–250ms. Speed of light in fibre is the floor —
  no architecture beats it, which is *why* you need edge/CDN/regional replicas.

**The move that scores:** convert an estimate into a decision. "80TB/year at
three replicas is ~240TB — too much for one node, so partitioning isn't optional,
it's forced. That means I need a partition key now, and the access pattern says
it should be user_id."

---

## Consistency decision tree

Do not apply one consistency model to the whole system. Classify per operation.

1. **Does a correctness invariant span multiple objects?** (balance ≥ 0,
   double-booking, uniqueness) → you need a transaction, and if the objects live
   on different partitions, either co-locate them under one partition key or
   accept a saga with compensations. Co-location is almost always cheaper.
2. **Does a user need to see their own write immediately?** → read-your-writes.
   Route that user's reads to the leader, or read from a cache written on the
   write path. This is far cheaper than global linearizability.
3. **Is it leader election, locking, or uniqueness?** → genuinely needs
   linearizability. Use a consensus system (etcd/ZooKeeper/Spanner). And use
   fencing tokens, because the lock holder can be paused arbitrarily.
4. **Everything else** → eventual/causal is fine. Say so explicitly and name the
   staleness window you're accepting.

Saying "strong consistency everywhere" reads as not having thought about cost.
Saying "eventual consistency" without naming what breaks reads as hand-waving.

---

## Reusable design patterns by problem shape

**Feed / timeline (Twitter, Instagram):** fan-out on write (precompute per-user
timeline, fast reads, expensive for celebrities) vs fan-out on read (cheap
writes, slow reads) vs **hybrid** — precompute for normal users, merge celebrity
posts at read time. The hybrid is the expected answer; the reasoning about the
celebrity tail is the actual signal.

**Chat / messaging:** WebSocket connection state, connection-to-server routing
via a registry, per-conversation ordering (sequence numbers, not wall clock),
delivery/read receipts, offline queue, fan-out for group chat.

**Rate limiter:** token bucket for burst tolerance; distributed counters in
Redis with local approximation to avoid a round trip per request; explain the
accuracy-vs-latency tradeoff.

**URL shortener / ID generation:** base62 of a counter vs hash-with-collision-
check; ID generation strategy (Snowflake/ULID); read-heavy so cache aggressively;
the interesting part is ID scheme and cache design, not the CRUD.

**Search / autocomplete:** inverted index, trie for prefixes, ranking, index
build pipeline as a batch job, near-real-time updates as a separate stream path.

**Nearby / geospatial:** geohash or S2/quadtree, cell-based search with ring
expansion, denormalized location index, hot cells in dense cities.

**Metrics / analytics ingestion:** high-volume append, time-series storage,
pre-aggregation and rollups, sketches (HLL/t-digest) for approximate queries,
downsampling and retention tiers.

**Payments / ledger:** idempotency keys, double-entry bookkeeping, exactly-once
*effects* via dedupe, saga for multi-party flows, audit trail, reconciliation as
a first-class batch job. Never claim exactly-once delivery; claim idempotent
effects.

**Object storage / file upload:** presigned URLs (never proxy bytes through your
API tier), multipart upload, CDN distribution, metadata in a database separate
from blobs.

**Notification system:** multi-channel dispatch, per-channel provider fallback,
rate limits per user, template management, dedupe, priority queues, DLQ.

---

## Tradeoff cheat sheet

Memorize the *shape* of these, not the words.

- **SQL vs NoSQL** → really: do you need multi-object transactions and flexible
  ad-hoc queries, or predictable horizontal scale on known access patterns?
- **Normalize vs denormalize** → write cost and consistency vs read cost and
  join elimination.
- **LSM vs B-tree** → write throughput and compression vs read predictability
  and stable latency.
- **Sync vs async replication** → durability vs write latency and availability.
- **Range vs hash partitioning** → range scans vs uniform load distribution.
- **Local vs global secondary index** → cheap writes/scatter-gather reads vs
  fast reads/distributed write cost.
- **Fan-out on write vs read** → read latency vs write amplification.
- **Cache-aside vs write-through** → simplicity/staleness vs write cost/freshness.
- **Batch vs stream** → throughput and simplicity vs freshness and complexity.
- **Orchestration vs choreography** → visibility/central coupling vs autonomy/
  debugging difficulty.
- **Monolith vs microservices** → simplicity and transactions vs independent
  deploy/scale and team autonomy, paid for in operational complexity.
- **Replication vs erasure coding** → read performance and simple recovery vs
  storage efficiency and expensive reconstruction.
- **Strong vs eventual consistency** → correctness simplicity vs availability,
  latency, and cross-region cost.

---

## Failure analysis checklist

Run this against your own design before the interviewer does:

- A single node dies — what's the detection time and the impact window?
- A whole AZ/region goes dark — what's the RPO/RTO?
- The database leader fails — who promotes, how is split-brain prevented?
- A dependency gets slow (not down) — do you have timeouts, or do threads pile up?
- Traffic spikes 10× — what saturates first? Do you shed, queue, or fall over?
- One key gets 1000× the traffic — where's the hot partition?
- A bad deploy ships — how fast is rollback, and does a schema change block it?
- A poison message arrives — DLQ, or infinite retry loop?
- Retries under partial failure — do they amplify and cause congestion collapse?
- The cache goes cold — can the origin survive the miss storm?

Naming the *detection signal* for each ("consumer lag alarm", "p99 breach on the
dependency", "queue depth growth") is a distinctly staff-level move.

---

## Things that quietly lose points

- Jumping to components before requirements — designing before knowing the shape.
- Reciting a stack ("Kafka, Redis, Cassandra") with no justification.
- Never saying "no" — a staff engineer scopes *out*.
- Ignoring the existing system; real staff work is migration, not greenfield.
- Claiming exactly-once delivery. It doesn't exist; idempotent effects do.
- Treating CAP as "pick two" — under a partition you choose C or A; the rest of
  the time the tradeoff is latency vs consistency (PACELC).
- Averaging percentiles across hosts. Mathematically meaningless.
- Adding a message queue with no answer for ordering, dedupe, or DLQ.
- Unbounded queues — that's a latency bug wearing a scalability costume.
- Microservices for a system with one team and no scale problem.
- Missing the hot-key/celebrity case in any social or multi-tenant design.
- Ignoring cost entirely.

---

## Phrases that carry signal

- "Let me separate what needs strong consistency from what doesn't."
- "The binding constraint here is X, so I'll design around that first."
- "I'd start simpler than this and only add Y when Z happens."
- "That's a reasonable alternative — I'd pick it if the workload were more W."
- "The failure mode I'm most worried about is ___, and I'd detect it with ___."
- "This is the part I'd prototype first, because it's the riskiest assumption."
- "At this scale that's fine; it breaks around ___, and then I'd ___."

---

## Drill questions

1. A design needs uniqueness on username. Why can't you enforce it with a
   Lamport timestamp scheme, and what's the minimum machinery that works?
2. Your p99 is 800ms but p50 is 20ms. List five distinct causes and how you'd
   distinguish them.
3. A service calls three dependencies with 3 retries each. Under a partial
   outage, what's the worst-case amplification, and how do you bound it?
4. Explain why a system stays down after the load spike that caused the outage
   has passed. What breaks the cycle?
5. When is a saga strictly worse than co-locating data under one partition key?
6. You must delete a user's data on request, but the system is event-sourced with
   immutable logs. What's your design?
7. Give a concrete case where snapshot isolation is insufficient and you need
   serializable.
8. Choose between fan-out on write and on read for a product where 0.1% of users
   have 10M followers. Justify with numbers.
9. Your cache hit rate drops from 95% to 85%. Quantify the origin load change.
10. How do you migrate a 5TB table to a new schema with zero downtime and a
    working rollback at every step?
11. A distributed lock protects a critical section, but a GC pause exceeds the
    lease. Show precisely how the corruption happens and how fencing stops it.
12. When would you choose erasure coding over 3× replication, and what do you
    give up?
