# System Design Mastery — Master Index

An exhaustive, revision-oriented reference of the concepts a Staff/Principal
engineer is expected to know. Every concept is written as the same five-part
card — **What / Use when / Advantages / Tradeoffs / Staff signal** — so the set
is scannable, comparable, and drillable.

Coverage spans the full data-intensive-systems curriculum (storage, replication,
partitioning, transactions, distributed-systems theory, consensus, batch and
stream processing) plus the practical infrastructure, architecture, operations,
security, and algorithmic material that interviews actually probe.

> These are standard industry concepts explained in original prose. Where a
> topic maps to a well-known textbook treatment, read the source for depth —
> this reference is for *recall and comparison*, not a substitute for it.

---

## Files

| # | File | Area |
|---|---|---|
| 01 | [Foundations & Estimation](01-foundations-and-estimation.md) | Reliability, scalability, percentiles, SLOs, back-of-envelope |
| 02 | [Data Models & Encoding](02-data-models-and-encoding.md) | Relational/document/graph, serialization, schema evolution |
| 03 | [Storage & Retrieval](03-storage-and-retrieval.md) | LSM vs B-tree, indexing, OLAP, column stores |
| 04 | [Replication](04-replication.md) | Leader/multi-leader/leaderless, quorums, conflict resolution |
| 05 | [Partitioning & Routing](05-partitioning-and-routing.md) | Sharding, consistent hashing, rebalancing, hot keys |
| 06 | [Transactions & Isolation](06-transactions-and-isolation.md) | ACID, isolation levels, anomalies, 2PC, sagas |
| 07 | [Distributed Faults & Time](07-distributed-faults-and-time.md) | Partial failure, clocks, pauses, fencing, Byzantine |
| 08 | [Consistency & Consensus](08-consistency-and-consensus.md) | Linearizability, CAP/PACELC, ordering, Raft/Paxos |
| 09 | [Batch & Stream Processing](09-batch-and-stream-processing.md) | MapReduce, dataflow, Kafka, CDC, windowing, exactly-once |
| 10 | [Caching & Delivery](10-caching-and-delivery.md) | Cache patterns, eviction, stampede, CDN, HTTP caching |
| 11 | [APIs, Networking & LB](11-apis-networking-and-load-balancing.md) | REST/gRPC/GraphQL, load balancing, pagination, push/pull |
| 12 | [Resilience Patterns](12-resilience-patterns.md) | Retries, circuit breakers, rate limiting, backpressure, DR |
| 13 | [Architecture & Services](13-architecture-and-services.md) | Monolith/microservices, DDD, CQRS, migration patterns |
| 14 | [Observability & Operations](14-observability-and-operations.md) | Metrics/logs/traces, SLOs, deploys, postmortems |
| 15 | [Security & Multi-Tenancy](15-security-and-multitenancy.md) | AuthN/AuthZ, encryption, tenancy models, privacy |
| 16 | [Algorithms & Building Blocks](16-algorithms-and-building-blocks.md) | Consistent hashing, sketches, CRDTs, geo/search indexes |
| 17 | [Interview Playbook](17-interview-playbook.md) | Structure, estimation kit, tradeoff sheet, failure checklist |

**Separate track:** [Agentic AI Mastery](../agentic-ai/a00-index.md) — 13 files
covering LLM foundations, context engineering, RAG, agent architectures, tools/MCP,
memory, evaluation, production reliability, safety, model adaptation, inference
infrastructure, and multi-agent systems. Same card format, drilled independently
with `revise --track agentic-ai`.

---

## How to use this

**Do not read it front to back.** Passive reading of reference material produces
recognition, not recall — and interviews test recall under pressure.

1. **Map the terrain once.** Skim the quick-reference table at the top of each
   file. Two hours, no notes. You now know what exists.
2. **Drill, don't re-read.** Each file ends with drill questions. Answer them out
   loud, from memory, before opening the file. The gap between what you can
   recognize and what you can produce *is* the study plan.
3. **Space the repetition.** A concept you recalled correctly doesn't need
   review tomorrow — it needs review in a week, then a month. Automated below.
4. **Attach concepts to real systems.** The daily digest in this repo delivers
   real engineering posts tagged by the same competencies. When you read how
   Netflix partitions a graph, connect it back to the partitioning cards. Paired
   concrete + abstract beats either alone.
5. **Practise the tradeoff sentence.** For any two related concepts, be able to
   say: *"I'd choose A over B when ___, because ___, and I'd switch when ___."*
   That sentence is what the interview is actually scoring.

### Suggested 8-week rotation

| Week | Focus | Paired practice |
|---|---|---|
| 1 | 01, 02 | Estimation drills; 2 design problems end-to-end |
| 2 | 03, 04 | Pick a storage engine for 3 different workloads and defend it |
| 3 | 05, 06 | Design a sharding scheme; walk every isolation anomaly |
| 4 | 07, 08 | Explain linearizability vs serializability without notes |
| 5 | 09, 16 | Design an ingestion pipeline; implement a sketch from scratch |
| 6 | 10, 11, 12 | Take an existing design and add failure handling throughout |
| 7 | 13, 14, 15 | Design a migration with rollback at every step |
| 8 | 17 + weak areas | Timed mock interviews, 45 min each |

---

## Master concept checklist

Tick only what you can *explain aloud with its tradeoff*. Recognition doesn't
count.

### Foundations
- [ ] Reliability; fault vs failure · [ ] Availability composition (series/parallel)
- [ ] Scalability; load parameters · [ ] Maintainability (operability/simplicity/evolvability)
- [ ] Vertical vs horizontal scaling · [ ] Shared-nothing / shared-disk / shared-memory
- [ ] Latency vs response time · [ ] Percentiles p50/p95/p99/p999 · [ ] Tail latency amplification
- [ ] Head-of-line blocking · [ ] Little's Law · [ ] Utilization→latency knee
- [ ] Amdahl's Law · [ ] Universal Scalability Law · [ ] Back-of-envelope numbers
- [ ] SLI/SLO/SLA · [ ] Error budgets · [ ] Graceful degradation · [ ] Chaos engineering

### Data models & encoding
- [ ] Relational · [ ] Document · [ ] Graph (property/triple) · [ ] Key-value · [ ] Wide-column
- [ ] Normalization vs denormalization · [ ] Impedance mismatch · [ ] Schema-on-read vs write
- [ ] Declarative vs imperative queries · [ ] MapReduce model
- [ ] JSON/XML limits · [ ] Thrift · [ ] Protocol Buffers · [ ] Avro
- [ ] Backward vs forward compatibility · [ ] Rolling-upgrade compatibility direction
- [ ] Dataflow via DB / service / message

### Storage & retrieval
- [ ] Log-structured storage · [ ] SSTable + memtable · [ ] LSM read/write path
- [ ] Compaction: size-tiered / leveled / time-window
- [ ] Write, read, space amplification · [ ] Bloom filter in reads
- [ ] B-tree structure + WAL · [ ] LSM vs B-tree tradeoff
- [ ] Clustered vs non-clustered index · [ ] Covering index · [ ] Composite index column order
- [ ] Selectivity/cardinality · [ ] Multi-dimensional index · [ ] R-tree
- [ ] In-memory stores · [ ] fsync/group commit · [ ] OLTP vs OLAP
- [ ] Star vs snowflake schema · [ ] Column store · [ ] RLE/bitmap/dictionary encoding
- [ ] Vectorized execution · [ ] Materialized views · [ ] Data cubes

### Replication
- [ ] Single-leader · [ ] Multi-leader · [ ] Leaderless
- [ ] Sync vs async vs semi-sync · [ ] Chain replication
- [ ] Failover; split brain · [ ] Statement / WAL / logical / trigger replication
- [ ] Replication lag · [ ] Read-your-writes · [ ] Monotonic reads · [ ] Consistent prefix reads
- [ ] Multi-leader topologies · [ ] LWW and its data loss · [ ] Version vectors · [ ] CRDTs · [ ] OT
- [ ] Quorums w+r>n · [ ] Why quorums aren't strong consistency
- [ ] Sloppy quorum + hinted handoff · [ ] Read repair · [ ] Anti-entropy + Merkle trees
- [ ] Happens-before / concurrency detection

### Partitioning
- [ ] Range partitioning · [ ] Hash partitioning · [ ] Consistent hashing + vnodes
- [ ] Rendezvous hashing · [ ] Skew and hot spots · [ ] Key salting
- [ ] Compound keys · [ ] Local vs global secondary index
- [ ] Rebalancing strategies · [ ] Request routing · [ ] Service discovery / gossip
- [ ] Resharding: dual write → backfill → cutover · [ ] Functional/vertical/horizontal partitioning

### Transactions
- [ ] ACID precisely · [ ] BASE · [ ] Single vs multi-object atomicity
- [ ] Read committed · [ ] Snapshot isolation / MVCC · [ ] Serializable
- [ ] Dirty read · [ ] Dirty write · [ ] Read skew · [ ] Lost update · [ ] Write skew · [ ] Phantom
- [ ] Compare-and-set · [ ] Materializing conflicts
- [ ] Serial execution · [ ] 2PL + predicate/index-range locks · [ ] SSI
- [ ] 2PC and in-doubt blocking · [ ] XA · [ ] Saga + compensation
- [ ] Outbox pattern · [ ] Idempotency keys

### Distributed faults & time
- [ ] Partial failure · [ ] Slow vs dead indistinguishability · [ ] Gray failure
- [ ] Timeout selection · [ ] Phi-accrual detection · [ ] Partially synchronous model
- [ ] Crash-stop / crash-recovery / Byzantine models · [ ] Safety vs liveness
- [ ] Monotonic vs wall clock · [ ] Clock skew · [ ] Lamport timestamps · [ ] Vector clocks
- [ ] Hybrid logical clocks · [ ] TrueTime + commit-wait
- [ ] Process pauses · [ ] Lease expiry hazard · [ ] Fencing tokens
- [ ] Heartbeats / gossip / SWIM

### Consistency & consensus
- [ ] Consistency spectrum ordering · [ ] Eventual consistency
- [ ] Linearizability · [ ] Serializability · [ ] **Difference between the two**
- [ ] Strict serializability · [ ] Sequential consistency · [ ] Causal consistency
- [ ] Session guarantees · [ ] CAP stated correctly · [ ] PACELC
- [ ] Total order broadcast · [ ] Consensus properties · [ ] FLP impossibility
- [ ] Paxos · [ ] Raft · [ ] Zab · [ ] Epochs + quorums
- [ ] ZooKeeper/etcd primitives · [ ] Correct distributed locking
- [ ] Coordination avoidance / CALM

### Batch & stream
- [ ] Online vs batch vs stream · [ ] MapReduce shuffle
- [ ] Sort-merge / broadcast hash / partitioned hash join · [ ] Join skew
- [ ] DAG engines · [ ] Lineage vs checkpointing
- [ ] Broker styles: JMS/AMQP vs log-based · [ ] Consumer groups · [ ] Offsets
- [ ] At-most/at-least/effectively-once · [ ] Consumer lag · [ ] DLQ
- [ ] CDC · [ ] Log compaction · [ ] Event sourcing · [ ] Immutability limits
- [ ] Stream-stream / stream-table joins · [ ] Event vs processing time
- [ ] Windows: tumbling/hopping/sliding/session · [ ] Watermarks · [ ] Late events
- [ ] Exactly-once mechanics · [ ] Lambda vs Kappa · [ ] Replay

### Caching & delivery
- [ ] Hit-ratio arithmetic · [ ] Cache-aside · [ ] Read-through · [ ] Write-through
- [ ] Write-behind · [ ] Write-around · [ ] Refresh-ahead
- [ ] LRU/LFU/ARC/W-TinyLFU · [ ] Scan resistance · [ ] TTL jitter
- [ ] Invalidation strategies · [ ] Stampede + single-flight · [ ] Penetration · [ ] Avalanche
- [ ] Hot keys · [ ] Local vs distributed cache · [ ] Cache warming
- [ ] CDN pull vs push · [ ] Cache key design · [ ] ETag / Cache-Control / stale-while-revalidate

### APIs, networking, load balancing
- [ ] L4 vs L7 · [ ] TCP vs UDP vs QUIC · [ ] TLS/mTLS cost · [ ] DNS TTL limits · [ ] Anycast
- [ ] LB algorithms · [ ] Power-of-two-choices · [ ] Health checks · [ ] Sticky sessions
- [ ] Connection pooling · [ ] Graceful shutdown/draining
- [ ] REST · [ ] gRPC · [ ] GraphQL + N+1 · [ ] API versioning
- [ ] Offset vs cursor pagination · [ ] Idempotency keys
- [ ] Long polling · [ ] SSE · [ ] WebSockets · [ ] Webhooks
- [ ] Fan-out on write vs read + hybrid

### Resilience
- [ ] Blast radius · [ ] Correlated failure · [ ] Active-active vs active-passive
- [ ] Timeout from percentiles · [ ] Backoff + jitter · [ ] Retry budgets · [ ] Retry amplification
- [ ] Circuit breaker states · [ ] Bulkhead · [ ] Cell-based architecture · [ ] Shuffle sharding
- [ ] Token/leaky bucket · [ ] Sliding window counters · [ ] Distributed rate limiting
- [ ] Load shedding · [ ] Admission control · [ ] Backpressure · [ ] Bounded queues
- [ ] Metastable failure / congestion collapse · [ ] Thundering herd on recovery
- [ ] RPO/RTO · [ ] Restore testing · [ ] Multi-region failover

### Architecture
- [ ] Modular monolith · [ ] Microservice costs · [ ] Distributed monolith
- [ ] Conway's Law · [ ] Bounded context · [ ] Aggregate as transaction boundary
- [ ] Database-per-service · [ ] CQRS · [ ] Choreography vs orchestration
- [ ] Strangler fig · [ ] Anti-corruption layer · [ ] BFF · [ ] Service mesh
- [ ] Serverless tradeoffs · [ ] Autoscaling signals · [ ] Stateless design
- [ ] Expand-contract migration · [ ] Shadow reads · [ ] Cost per request

### Observability & ops
- [ ] Metrics vs logs vs traces · [ ] Histogram vs summary · [ ] **Never average percentiles**
- [ ] Cardinality explosion · [ ] Trace context propagation · [ ] Head vs tail sampling
- [ ] RED · [ ] USE · [ ] Four golden signals · [ ] Burn-rate alerts
- [ ] Symptom vs cause alerting · [ ] Blameless postmortem · [ ] DORA metrics
- [ ] Rolling/blue-green/canary · [ ] Feature flags · [ ] Rollback vs roll-forward
- [ ] Online schema change · [ ] Backfill throttling

### Security & tenancy
- [ ] AuthN vs AuthZ · [ ] Session vs token · [ ] OAuth2 flows · [ ] OIDC
- [ ] JWT revocation problem · [ ] mTLS · [ ] Zero trust
- [ ] RBAC vs ABAC vs ReBAC · [ ] Least privilege · [ ] Secrets rotation · [ ] Envelope encryption
- [ ] Password hashing · [ ] Injection/SSRF/IDOR/XSS/CSRF
- [ ] DDoS layers · [ ] Audit logging · [ ] PII classification
- [ ] Right-to-deletion vs immutable logs (crypto-shredding) · [ ] Data residency
- [ ] Silo vs pooled tenancy · [ ] Row-level security · [ ] Per-tenant quotas

### Algorithms & building blocks
- [ ] Consistent hashing internals · [ ] Bloom filter sizing · [ ] Cuckoo filter
- [ ] HyperLogLog · [ ] Count-Min Sketch · [ ] Reservoir sampling · [ ] t-digest
- [ ] Merkle tree · [ ] Skip list · [ ] Trie/radix tree
- [ ] Inverted index · [ ] TF-IDF/BM25 · [ ] ANN: HNSW/IVF/PQ
- [ ] Geohash · [ ] Quadtree · [ ] R-tree · [ ] S2/H3
- [ ] UUIDv4 vs ULID/UUIDv7 index locality · [ ] Snowflake IDs
- [ ] Gossip/SWIM · [ ] CRDT families + tombstone growth · [ ] OT vs CRDT
- [ ] Compression tradeoffs · [ ] Checksums / end-to-end argument
- [ ] Erasure coding vs replication

---

## Competency mapping

These files align with the twelve competencies used by the daily digest in this
repo, so reading and revision reinforce each other:

| Competency | Primary files |
|---|---|
| distributed-systems | 07, 08 |
| storage-and-data | 02, 03 |
| caching | 10 |
| queues-and-streaming | 09 |
| scale-and-performance | 01, 05 |
| reliability-and-incidents | 12, 14 |
| observability | 14 |
| migrations | 13 |
| architecture-and-apis | 11, 13 |
| security-and-multitenancy | 15 |
| infra-and-cost | 01, 13 |
| ml-systems | 16 (ANN/vector search) |
