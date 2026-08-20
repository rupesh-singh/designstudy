# 9. Batch & Stream Processing

Data processing architectures fall into three categories distinguished by latency expectations: online services (respond immediately), batch systems (process accumulated data periodically), and stream systems (process data continuously with low latency). Understanding when and how to combine these paradigms — and the guarantees each can provide around ordering, completeness, and exactly-once semantics — is a core staff-level skill.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Services / batch / stream | Three processing paradigms with different latency/throughput SLIs | Choosing architecture for a data pipeline |
| MapReduce | Batch processing via distributed sort-shuffle-reduce on disk | Understanding Hadoop legacy; contrast with modern engines |
| Dataflow engines (Spark/Flink) | DAG-based execution; pipeline stages without full materialization | Building efficient batch or stream pipelines |
| Log-based brokers (Kafka) | Durable, partitioned, replayable event log | Event sourcing, CDC, stream processing input |
| AMQP-style brokers (RabbitMQ) | Transient message routing with per-message acknowledgment | Task queues, work distribution, fan-out |
| Change data capture (CDC) | Streaming database changes as events | Keeping derived data in sync, search index updates |
| Event sourcing | Persisting domain events; deriving state by replay | Audit trails, temporal queries, CQRS |
| Stream joins | Combining streams/tables in real-time | Enrichment, sessionization, correlation |
| Windowing | Grouping unbounded data into finite chunks for aggregation | Time-based analytics on streams |
| Watermarks | Progress indicators for event-time completeness | Deciding when a window can be closed |
| Exactly-once semantics | Preventing duplicates in output despite failures | Financial transactions, counters, billing |
| Lambda / Kappa architecture | Combining batch and stream for correctness and freshness | Deciding pipeline topology |

## Batch Processing

### Unix Philosophy and Composable Pipelines
**What.** The Unix model of small, single-purpose programs connected by a uniform interface (byte streams via stdin/stdout) with immutable inputs provides the conceptual foundation for batch processing. MapReduce and its successors extend this to distributed scale: the "pipes" become distributed file systems, and the programs become parallelized tasks.
**Use when.** Justifying design choices like immutable intermediate datasets, schema-on-read, and the separation of computation logic from wiring.
**Advantages.**
- Immutable inputs make retry/reprocessing trivially safe
- Uniform interfaces enable arbitrary composition without modifying components
- Separation of logic from orchestration enables independent scaling and testing
**Tradeoffs.**
- Rigid: each stage must finish before the next begins (in classic MapReduce)
- Data serialization/deserialization at every boundary adds overhead
**Staff signal.** The power of the Unix philosophy in data systems is not the byte-stream format — it is the contract of immutability and idempotency that makes fault tolerance free: any failed stage can be rerun without side effects.

### MapReduce Execution Model
**What.** MapReduce processes data in three phases: Map (transform input records into key-value pairs), Shuffle (partition and sort by key across the network), Reduce (aggregate all values for a given key). Intermediate results are written to disk between stages, providing fault tolerance at the cost of I/O.
**Use when.** Understanding the foundational batch model; recognizing why it has been superseded by DAG-based engines.
**Advantages.**
- Simple programming model: user writes only map and reduce functions
- Fault tolerance via disk materialization: any failed task reruns from its input split
- Handles datasets far exceeding memory by streaming through data
**Tradeoffs.**
- Full materialization to disk between every stage: enormous I/O overhead for multi-stage pipelines
- No pipelining: downstream stages wait for upstream to fully complete
- Chaining multiple MapReduce jobs is clumsy and inefficient
**Staff signal.** MapReduce's materialization strategy trades latency for fault tolerance. Modern engines (Spark, Flink) achieve the same fault tolerance through lineage-based recomputation or periodic checkpoints without the disk I/O penalty for intermediate state.

### Distributed Joins in Batch
**What.** Sort-merge join: both datasets are partitioned by join key and sorted; co-located partitions are merged. Broadcast hash join: the smaller dataset is broadcast to all nodes and held in a hash table; large dataset streams through. Partitioned hash join: both datasets are partitioned identically by join key; each partition joins independently.
**Use when.** Choosing join strategy based on relative dataset sizes and key distribution.
**Advantages.**
- Sort-merge: handles arbitrarily large datasets on both sides
- Broadcast hash: eliminates shuffle of large dataset when one side fits in memory
- Partitioned hash: avoids broadcast when both sides are already co-partitioned
**Tradeoffs.**
- Sort-merge: expensive shuffle and sort for both sides
- Broadcast hash: fails if "small" side does not fit in memory; network cost of broadcasting
- Hot keys (skew) can overload a single reducer in any partition-based strategy
**Staff signal.** Skew handling is the real-world concern: techniques include salting hot keys (appending random suffixes to spread load, then aggregating), replicating the small side to all partitions of the hot key, or isolating hot keys for separate processing.

### Dataflow Engines: Spark, Flink, Tez
**What.** These engines represent computation as a directed acyclic graph (DAG) of operators rather than rigid map-then-reduce phases. They can pipeline data between operators without materializing to disk, only materializing at shuffle boundaries. Fault tolerance comes from lineage (Spark: recompute lost partitions from parent RDDs) or checkpointing (Flink: periodic distributed snapshots).
**Use when.** Any non-trivial batch or streaming pipeline; they have effectively replaced raw MapReduce.
**Advantages.**
- Orders of magnitude faster than chained MapReduce for iterative workloads (ML, graph algorithms)
- Unified batch+stream API (Flink especially)
- Flexible: supports arbitrary operator graphs, not just map→reduce
**Tradeoffs.**
- Lineage-based recovery can be expensive for long chains (recomputes from last materialization)
- Memory pressure: pipelining keeps more data in memory simultaneously
- Complexity of tuning shuffle partitions, memory fractions, parallelism
**Staff signal.** The key insight is that materialization is a fault-tolerance mechanism, not a correctness requirement. By making it optional and strategic (only at expensive shuffle boundaries), dataflow engines get both performance and recovery guarantees.

### Batch Output Patterns
**What.** Batch jobs typically produce immutable output artifacts: search indexes, precomputed key-value stores, aggregate tables, or ML model files. Because output is immutable and complete, rollback is trivial: point consumers at the previous version.
**Use when.** Building derived data systems (Elasticsearch indexes, recommendation caches, materialized views).
**Advantages.**
- Atomic switchover: new output replaces old atomically; no partial states visible
- Easy A/B testing: serve from version A or version B in parallel
- Safe to rerun: idempotent by construction (output replaces, not appends)
**Tradeoffs.**
- Full recomputation for every update (unless incrementalized)
- Latency: output is only as fresh as the last batch run
**Staff signal.** This pattern — immutable, versioned, atomically-swapped outputs — is why batch systems are often more operationally reliable than systems that mutate state in place. The cost is latency; stream processing addresses this.

## Message Brokers and Event Streams

### AMQP/JMS-style vs Log-based Brokers
**What.** AMQP-style brokers (RabbitMQ, ActiveMQ) route messages to consumers, delete them on acknowledgment, and support per-message routing, priority, and load-balanced consumption. Log-based brokers (Kafka, Pulsar) append messages to a durable, partitioned, ordered log; consumers track their own offset; messages are retained regardless of consumption.
**Use when.** AMQP: task queues, work distribution where each message is processed once by one worker. Log-based: event streaming where multiple consumers need the full ordered history, replay, and independent read positions.
**Advantages.**
- AMQP: flexible routing (topic, direct, fanout), per-message backpressure, simple semantics
- Log-based: replay from any point, multiple independent consumers, ordering within partition, indefinite retention
**Tradeoffs.**
- AMQP: no replay (message deleted on ack); ordering only within a single queue; fan-out duplicates messages
- Log-based: ordering only within a partition; consumer parallelism limited by partition count; partition rebalancing is disruptive
**Staff signal.** The fundamental distinction: AMQP treats messages as ephemeral tasks to be dispatched; Kafka treats messages as facts in an immutable log. This determines everything downstream — replay capability, consumer independence, and the ability to derive new views from historical data.

### Consumer Groups, Partitions, and Ordering
**What.** In Kafka, a consumer group assigns each partition to exactly one consumer instance: this guarantees per-partition ordering and enables parallel consumption up to the partition count. More consumers than partitions means some sit idle; fewer means some handle multiple partitions.
**Use when.** Scaling stream consumers while preserving order for related events (e.g., all events for a user on the same partition).
**Advantages.**
- Simple scaling model: add consumers up to partition count
- Ordering guarantee per partition enables stateful processing of keyed data
**Tradeoffs.**
- Maximum parallelism equals partition count — increasing requires repartitioning
- Rebalancing on consumer join/leave causes temporary processing pauses
- Hot partitions (skewed key distribution) create uneven load
**Staff signal.** Partition count is a capacity decision made at topic creation that is expensive to change later. Over-partition early (Kafka handles thousands of partitions) rather than under-partitioning and needing to repartition with data migration.

### Offset Management and Delivery Semantics
**What.** At-most-once: commit offset before processing (may lose messages on crash). At-least-once: commit offset after processing (may reprocess on crash). Effectively-once: combine at-least-once delivery with idempotent processing or transactional output (Kafka transactions, which atomically commit offsets and output together).
**Use when.** Choosing delivery guarantees based on the cost of duplicates vs the cost of message loss.
**Advantages.**
- At-least-once + idempotence: simplest path to effectively-once without protocol complexity
- Kafka transactions: atomic offset + output commit when both are in Kafka
**Tradeoffs.**
- True exactly-once across heterogeneous systems (Kafka → external DB) requires the external system to participate in deduplication
- Transactional writes add latency (~10–50 ms for Kafka transactions)
**Staff signal.** "Exactly-once" is often "effectively-once": the system may process a message multiple times internally, but the externally visible effect is as if it processed it once. The mechanism is always one of: idempotent output, transactional atomic commit, or deduplication at the sink.

### Backpressure, Consumer Lag, and Dead Letter Queues
**What.** Consumer lag is the offset distance between the most recently produced message and the most recently consumed message. Growing lag means consumers cannot keep up. Backpressure propagates this signal upstream to slow producers. Dead letter queues (DLQs) capture messages that fail processing after retries, preventing poison pills from blocking the pipeline.
**Use when.** Monitoring stream health; designing retry and error-handling strategies.
**Advantages.**
- Lag monitoring provides early warning of capacity problems before data loss
- DLQs isolate failures without halting the main pipeline
**Tradeoffs.**
- Backpressure in Kafka is implicit (consumer just falls behind) rather than explicit — producers are not throttled
- DLQ messages require separate reprocessing logic and monitoring
**Staff signal.** In Kafka, unlike reactive streams, there is no built-in backpressure to producers. If consumers fall behind beyond retention, data is lost (log compaction or TTL expiry). The operational imperative is monitoring lag and scaling consumers before retention is breached.

## Change Data Capture and Event Sourcing

### Change Data Capture (CDC)
**What.** CDC captures row-level changes (inserts, updates, deletes) from a database's transaction log and publishes them as an ordered stream of events. Consumers rebuild derived views (search indexes, caches, analytics stores) from this stream. Initial bootstrapping uses a consistent snapshot followed by streaming changes from the snapshot's log position.
**Use when.** Keeping derived data stores in sync without dual-write inconsistency; migrating data between systems; building real-time materialized views.
**Advantages.**
- No dual-write problem: single source of truth writes to the database; all derivations come from the log
- Ordering and transactional consistency preserved from the source
- Enables replay and bootstrapping of new consumers from the beginning of time (with log compaction)
**Tradeoffs.**
- Depends on database-specific log format (PostgreSQL WAL, MySQL binlog); coupling to internals
- Schema evolution in the source propagates complexity to all consumers
- Log retention and compaction must be managed
**Staff signal.** CDC with log compaction (Kafka) effectively turns a mutable database into an immutable event log — the log-compacted topic retains the latest value per key indefinitely, enabling any new consumer to bootstrap without a separate snapshot process.

### Event Sourcing
**What.** Instead of storing current state, persist every domain event (commands that have been validated and accepted) as an immutable, append-only log. Current state is derived by replaying the event sequence. Snapshotting periodically avoids replaying the entire history.
**Use when.** Audit-critical domains (finance, healthcare), systems requiring temporal queries ("what was the state at time T"), or CQRS architectures where read and write models differ.
**Advantages.**
- Complete audit trail by construction
- Enables temporal queries and what-if analysis by replaying with different logic
- Decouples write model (events) from read model (projections) — each optimized independently
**Tradeoffs.**
- Evolving event schemas is hard — old events must remain interpretable
- Replay time grows unboundedly without snapshotting
- GDPR "right to erasure" conflicts with immutability (requires crypto-shredding or redaction)
- Eventual consistency between event log and projections
**Staff signal.** The critical distinction: a command is a request that may be rejected; an event is a fact that has occurred. Event sourcing stores events, not commands. This means validation logic lives at the command handler, and events are unconditionally applicable during replay.

## Stream Processing

### Stream Joins
**What.** Stream-stream join: correlate two event streams within a time window (e.g., match ad impressions with clicks within 30 minutes). Stream-table join (enrichment): enrich each stream event with lookup data from a table (e.g., add user profile to click events). Table-table join: maintain a materialized join of two tables that both update over time.
**Use when.** Real-time enrichment, sessionization, correlation of events from different sources.
**Advantages.**
- Stream-table join: real-time enrichment without batch ETL delay
- Stream-stream join: detect patterns (fraud, correlation) as they happen
**Tradeoffs.**
- Stream-stream joins require buffering state for the window duration — memory cost proportional to window × throughput
- Late events arriving after the window closes are either dropped or trigger retractions
- Slowly changing dimensions: if the table changes between event time and processing time, which version do you join against?
**Staff signal.** The slowly-changing dimension problem is subtle: an order placed at 10:00 should join against the product price at 10:00, not the current price at processing time (10:05). Solving this requires versioned table state indexed by event time, which is expensive.

### Time: Event Time vs Processing Time
**What.** Event time is when the event actually occurred (embedded in the event by the producer). Processing time is when the system processes it. These can differ by seconds to hours (mobile devices offline, network delays, reprocessing historical data). Correct results for windowed aggregations require event time; processing time is simpler but gives non-deterministic, non-reproducible results.
**Use when.** Any windowed aggregation, sessionization, or time-based join.
**Advantages.**
- Event time: deterministic, reproducible results regardless of when processing happens; correct for reprocessing
- Processing time: no watermark complexity, no late-event handling needed
**Tradeoffs.**
- Event time requires watermarks to know when a window is "complete" — inherently uncertain
- Buffering for late events consumes memory and delays output
**Staff signal.** The fundamental tension: event time gives correct results but you can never be sure all events have arrived (completeness vs latency). Processing time gives timely results but they change depending on when you run the computation — making reprocessing produce different results than the original run.

### Windows: Tumbling, Hopping, Sliding, Session
**What.** Tumbling: fixed-size, non-overlapping (e.g., every 5 minutes). Hopping: fixed-size, overlapping (5-minute window every 1 minute). Sliding: triggered by event activity within a range. Session: dynamically-sized windows closed by an inactivity gap (e.g., user session ends after 30 minutes of no activity).
**Use when.** Aggregating unbounded streams into finite, processable chunks.
**Advantages.**
- Tumbling: simplest; each event belongs to exactly one window
- Session: captures real user behavior without fixed time boundaries
**Tradeoffs.**
- Hopping windows produce more output (every event appears in multiple windows)
- Session windows require per-key state and cannot be closed until the gap timer fires (memory pressure)
**Staff signal.** Session windows are the most operationally challenging because their size is data-dependent and unbounded — a single active user can keep a session window open indefinitely, consuming memory until the gap timeout.

### Watermarks and Late Events
**What.** A watermark is the system's estimate of event-time progress: "I believe all events with timestamp ≤ W have arrived." Events arriving after the watermark passes their window are "late." The allowed lateness parameter controls how long to keep window state for late arrivals. The tradeoff: aggressive watermarks produce timely but potentially incomplete results; conservative watermarks produce complete but delayed results.
**Use when.** Deciding when to emit window results in event-time processing.
**Advantages.**
- Makes the completeness/latency tradeoff explicit and tunable per pipeline
- Enables handling late data gracefully (retractions, updates to previous results)
**Tradeoffs.**
- No watermark can be perfect — it is always a heuristic (max event time - allowed lateness)
- Keeping state for late arrivals consumes memory proportional to allowed lateness
- Very late events (beyond allowed lateness) are dropped — data loss by design
**Staff signal.** Google Dataflow's contribution was making watermarks a first-class concept with triggers (when to emit) and accumulation modes (discard, accumulate, retract). The key operational question is: what is the business cost of a late event being dropped vs the infrastructure cost of keeping state longer?

### Exactly-Once and Fault Tolerance
**What.** Achieving effectively-once semantics in stream processing requires ensuring that failures do not cause duplicate or missing output. Mechanisms: (1) Idempotent writes (output operation is naturally idempotent or uses deduplication keys), (2) Transactional writes (atomically commit processing progress and output), (3) Distributed snapshots (Chandy-Lamport style — Flink's checkpointing: periodically snapshot all operator state consistently).
**Use when.** Billing, financial aggregations, counters — anywhere duplicates cause business-visible errors.
**Advantages.**
- Flink checkpointing: exactly-once with low overhead (barriers flow through the DAG without stopping processing)
- Kafka transactions + idempotent producers: end-to-end exactly-once within Kafka ecosystem
**Tradeoffs.**
- Checkpointing adds latency proportional to state size during barrier alignment
- External systems (databases, APIs) must participate in idempotence or transactions
- Microbatching (Spark Structured Streaming) achieves exactly-once but at the cost of minimum batch-interval latency
**Staff signal.** Chandy-Lamport distributed snapshots work by injecting barrier markers into the data stream. When an operator receives barriers from all inputs, it snapshots its state. Recovery rolls back to the last complete snapshot. The elegance is that no global pause is needed — the barriers flow naturally with the data.

## Architecture Patterns

### Lambda vs Kappa Architecture
**What.** Lambda architecture maintains two parallel pipelines: a batch layer (reprocesses all historical data periodically for correctness) and a speed layer (processes recent events with lower latency). Results are merged at query time. Kappa architecture uses only a stream processor, achieving correctness through replay: reprocess historical data by re-reading the event log from the beginning.
**Use when.** Choosing between maintaining two codepaths (Lambda) or one codepath with replay capability (Kappa).
**Advantages.**
- Lambda: batch layer provides a "ground truth" that corrects speed layer approximations
- Kappa: single codebase, no divergence between batch and streaming logic
**Tradeoffs.**
- Lambda: maintaining two codepaths (batch and stream) doing the same computation is an enormous operational burden; divergence bugs are inevitable
- Kappa: requires the stream processor to handle full historical replay at batch-like scale; log must be retained indefinitely or snapshottable
**Staff signal.** The Lambda architecture's maintenance cost is the killer: every business logic change must be implemented twice, tested twice, and the merge logic at the serving layer adds a third source of bugs. Kappa wins operationally whenever the stream processor can handle historical replay throughput.

### Reprocessing and Replay as First-Class
**What.** Treating the event log as the authoritative data source means any derived view can be rebuilt by replaying from the log. This enables: fixing bugs in processing logic (reprocess with corrected code), adding new derived views retroactively, and migrating between systems without data loss.
**Use when.** Building data pipelines that must evolve over time; ensuring recoverability from logical errors (not just infrastructure failures).
**Advantages.**
- Logical errors are recoverable: fix the code and rerun
- New consumers get the full history without special migration tooling
- A/B testing of pipeline logic on the same data
**Tradeoffs.**
- Requires indefinite log retention (or periodic compacted snapshots)
- Reprocessing takes time proportional to history size — may take hours/days for large datasets
- Must handle the "thundering herd" when reprocessing catches up and merges with real-time
**Staff signal.** The ability to reprocess is what makes immutable logs so powerful: you separate the "facts" (what happened) from the "interpretation" (how you process it). Facts are stable; interpretations evolve. This is the core insight of the "unbundled database" architectural philosophy.

### Unbundling the Database
**What.** A traditional database bundles storage, indexing, query execution, caching, and materialized views into one system. The "unbundled" approach composes these from separate components connected by event streams: a durable log (Kafka) feeds specialized stores (Elasticsearch for search, Redis for cache, PostgreSQL for queries). Each derived store is a materialized view of the log.
**Use when.** Building systems where no single database serves all access patterns; evolving architecture without big-bang migrations.
**Advantages.**
- Each component is best-of-breed for its access pattern
- Adding a new derived view requires only a new consumer, not schema changes to the source
- Fault isolation: one derived store's failure does not affect others
**Tradeoffs.**
- Eventually consistent between log and derived stores (propagation delay)
- Operational complexity: many systems to monitor, many potential failure points
- End-to-end exactly-once delivery across heterogeneous systems is very hard
**Staff signal.** This architecture treats the log as the system of record (like a database's WAL) and all queryable stores as secondary indexes. The insight: a database already works this way internally — we are just exposing the architecture explicitly and composing it from independent services.

## Common interview traps

- Saying "Kafka guarantees exactly-once delivery" without qualification — it guarantees it within the Kafka ecosystem (producers + consumer offsets); external sinks require idempotence or transactions.
- Confusing event time with processing time and not realizing that reprocessing historical data with processing-time windows produces different results each time.
- Claiming MapReduce is obsolete without acknowledging that its fault-tolerance-through-materialization idea persists in shuffle stages of Spark/Flink.
- Describing CDC as "just database triggers" — triggers execute synchronously and couple consumers to the source; CDC is asynchronous and decoupled.
- Stating Lambda architecture is "batch plus streaming" without identifying the core problem: dual-codebase maintenance and merge-layer complexity.
- Saying "watermarks solve the late event problem" — they don't solve it; they make the tradeoff explicit (you still lose events beyond allowed lateness).
- Confusing backpressure (explicit upstream throttling) with consumer lag (implicit falling behind) in Kafka — Kafka does not propagate backpressure to producers.
- Treating event sourcing and CDC as the same thing — event sourcing is a domain modeling choice; CDC extracts change events from a database that stores mutable state.

## Drill questions

1. You have a Kafka topic with 12 partitions and a consumer group with 15 instances. What happens? What if you have 8 instances?
2. A stream-stream join correlates ad impressions with clicks within a 1-hour window. Your system processes 100K impressions/second. Estimate the state size and describe what happens to memory as event-time skew increases.
3. Explain why Flink's Chandy-Lamport checkpointing can provide exactly-once without stopping the pipeline. What is the cost during checkpoint alignment?
4. A team is building a search index derived from a database via dual writes (write to DB and to Elasticsearch). Describe the failure mode and propose the CDC-based alternative.
5. Why does session-window processing create memory pressure problems that tumbling windows do not? What bounds can you set?
6. You are reprocessing 6 months of events through a Kappa-architecture pipeline. How do you handle the transition point where reprocessing catches up to real-time?
7. Compare Spark's lineage-based fault tolerance with Flink's checkpointing. Under what workload characteristics does each approach win?
8. A batch job builds a recommendation model daily. The business wants results within 5 minutes of new data. Describe the architecture options and their tradeoffs.
9. Explain the slowly-changing dimension problem in stream-table joins. How would you implement a solution that joins against the version of the table valid at event time?
10. Why does the "unbundled database" architecture introduce eventual consistency between derived views? When is this acceptable and when is it not?
