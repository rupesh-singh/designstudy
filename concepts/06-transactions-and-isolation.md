# 6. Transactions & Isolation

Transactions group multiple read-write operations into a logical unit that either fully succeeds or fully fails, with controlled visibility of intermediate state to other concurrent operations. The core challenge is balancing correctness guarantees against performance and availability. Most production bugs in data systems trace to misunderstanding which anomalies your chosen isolation level actually permits.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| ACID | Property bundle: atomic commit, invariant preservation, concurrent isolation, durable persistence | Reasoning about what a database actually guarantees |
| BASE | Basically Available, Soft state, Eventually consistent — distributed systems alternative | Designing for availability over strict consistency |
| Read committed | No dirty reads, no dirty writes | Default isolation in most databases (PostgreSQL, Oracle) |
| Snapshot isolation (MVCC) | Each transaction sees a consistent point-in-time snapshot | Avoiding read skew in long-running reads |
| Lost update | Two concurrent read-modify-writes; one overwrites the other | Counter increments, balance transfers, any RMW cycle |
| Write skew | Two transactions read overlapping data, make disjoint writes that together violate a constraint | On-call scheduling, booking, any check-then-act |
| Phantom | A write in one transaction changes the set of rows matching another's WHERE clause | Range-based constraints and aggregation queries |
| Serial execution | Run transactions one at a time, sequentially | Absolute simplicity if throughput permits (VoltDB, Redis) |
| Two-phase locking (2PL) | Acquire all locks before release; prevents all anomalies | When serializability is required and workloads fit lock granularity |
| SSI | Optimistic: execute concurrently, detect conflicts at commit | Serializable without blocking; tolerant of read-heavy workloads |
| 2PC | Distributed atomic commit via prepare/commit protocol | Cross-partition or cross-service atomic operations |
| Saga | Long-lived distributed transaction via compensating actions | Microservices coordination without distributed locking |
| Outbox pattern | Atomically write event + data in one DB transaction | Solving the dual-write problem for event-driven systems |
| Idempotency keys | Client-generated unique key ensures at-most-once processing | Safe retries without duplicate side effects |

## ACID and BASE

### ACID Precisely

**What.** Atomicity: all operations in a transaction commit together or all roll back — no partial application. Consistency: a transaction moves the database from one valid state to another, preserving application-defined invariants (this is actually an application responsibility, not a database mechanism). Isolation: concurrently executing transactions don't observe each other's intermediate state (the degree depends on isolation level). Durability: once committed, data survives crashes (typically via WAL + fsync).

**Use when.** Any operation where partial failure would leave data in a corrupt or inconsistent state.

**Advantages.**
- Simplifies application logic — developers reason about sequential execution
- Guarantees recoverability after crashes

**Tradeoffs.**
- "ACID" is marketing-elastic — databases vary enormously in what they actually provide (Oracle's "serializable" is actually snapshot isolation)
- Durability is not absolute: disk corruption, firmware bugs, and simultaneous replica loss can still lose committed data
- Stronger isolation costs throughput — serializable can be 10-100× slower than read committed for contended workloads

**Staff signal.** The "C" in ACID is fundamentally different from the other three — it's an application-level invariant, not something the database mechanism enforces. The database can't know your business rules.

### BASE as Contrast

**What.** Basically Available (system always responds, possibly with stale data), Soft state (state may change without input due to eventual convergence), Eventually consistent (given no new writes, all replicas converge). It describes the tradeoff space chosen by most distributed NoSQL systems.

**Use when.** You've chosen availability over consistency (AP in CAP terms) and must characterize what guarantees remain.

**Advantages.**
- Enables horizontal scaling and partition tolerance without blocking writes
- Higher throughput and availability than strict ACID in distributed settings

**Tradeoffs.**
- Application must handle stale reads, conflicts, and temporary inconsistency
- "Eventually" has no time bound — convergence could take milliseconds or hours

**Staff signal.** BASE is not really an alternative to ACID — it's an acknowledgment that you're giving up some ACID properties in exchange for availability. The real question is always: which specific properties are you relaxing, and what application-level mechanisms compensate?

## Single-Object vs Multi-Object Operations

### Why Multi-Object Atomicity Matters

**What.** Single-object atomicity (e.g., atomic writes to one row) is provided by almost all databases via hardware-level compare-and-swap or WAL. Multi-object atomicity ensures that writes to multiple rows, tables, or indexes either all commit or none do.

**Use when.** Most real operations touch multiple objects: inserting a row and updating an index, transferring between two accounts, writing a foreign-key reference and the referenced row.

**Advantages.**
- Without multi-object atomicity, you get dangling references, partially applied updates, and corrupted denormalized data

**Tradeoffs.**
- Multi-object transactions require coordination (locking or MVCC bookkeeping) that limits concurrency
- In distributed systems, multi-partition transactions require protocols like 2PC, with significant latency cost

**Staff signal.** Many NoSQL databases initially launched without multi-object transactions, claiming they weren't needed. Most (MongoDB, Cassandra, DynamoDB) eventually added them because application developers can't reliably build correct multi-object operations without database support.

### Error Handling and Retries

**What.** When a transaction aborts (deadlock, constraint violation, transient failure), retrying is the standard recovery path. But retrying is not always safe.

**Use when.** Any transaction-based application must have a retry strategy, but must also know when retrying is dangerous.

**Advantages.**
- Simple retries handle transient failures (network glitch, deadlock victim selection) gracefully

**Tradeoffs.**
- Unsafe to retry if: the transaction succeeded but the acknowledgment was lost (causes duplicate execution); the failure is due to overload (retry amplifies the problem); side effects outside the transaction (emails sent) can't be rolled back
- Retry storms: many clients retrying simultaneously after a transient outage can create a thundering herd

**Staff signal.** The idempotency key pattern is the structural solution to the "did it actually commit?" ambiguity — the server deduplicates based on a client-provided unique key, making retries safe regardless of whether the original succeeded.

## Isolation Levels

### Read Committed

**What.** Two guarantees: (1) No dirty reads — you only see data that has been committed. (2) No dirty writes — you only overwrite data that has been committed (row-level write locks held until commit). This is the default in PostgreSQL and Oracle.

**Use when.** The baseline isolation level for most OLTP workloads — prevents the most egregious anomalies without heavy locking.

**Advantages.**
- Prevents dirty reads (no seeing uncommitted data) and dirty writes (no clobbering uncommitted changes)
- Minimal performance overhead — short-duration row locks for writes, MVCC for reads

**Tradeoffs.**
- Permits read skew (non-repeatable reads): reading the same row twice in one transaction may yield different values
- Permits lost updates: two read-modify-write cycles can clobber each other
- Permits write skew: check-then-act patterns can violate constraints

**Staff signal.** Read committed is deceptively weak — it prevents only the anomalies that would make the system blatantly broken (seeing garbage data), not the subtle ones that corrupt business logic.

### Snapshot Isolation / MVCC

**What.** Each transaction reads from a consistent snapshot of the database taken at transaction start. Writes create new versions; reads never block writes and vice versa. Implemented via Multi-Version Concurrency Control (MVCC): each row has multiple versions tagged with transaction IDs; visibility rules determine which version a transaction sees.

**Use when.** Long-running read transactions (analytics, reports, backups) that must see consistent data without blocking concurrent writes. PostgreSQL's "REPEATABLE READ" is actually snapshot isolation.

**Advantages.**
- Readers never block writers; writers never block readers — excellent read concurrency
- Consistent snapshots enable reliable backups without pausing writes
- Eliminates read skew (non-repeatable reads)

**Tradeoffs.**
- Still permits write skew and phantoms (two transactions read overlapping data, then make conflicting writes)
- MVCC storage overhead: old versions must be retained until no transaction can see them (vacuum/garbage collection)
- Does not prevent lost updates in all implementations (PostgreSQL detects them; Oracle/MySQL don't always)

**Staff signal.** "Snapshot isolation" and "repeatable read" are used interchangeably by PostgreSQL but are technically different in the SQL standard — this naming confusion is a frequent source of interview errors and production bugs.

### Indexes and Snapshot Isolation

**What.** Under MVCC, indexes must handle multiple versions of the same row. Two approaches: point the index to all versions and filter by visibility at read time, or maintain version-specific index entries with transaction-ID-based filtering.

**Use when.** Understanding why MVCC has storage/performance overhead in index-heavy workloads.

**Advantages.**
- PostgreSQL's approach (index points to heap tuple, visibility check at tuple) keeps indexes simpler
- Append-only B-trees (CouchDB-style) avoid in-place updates entirely

**Tradeoffs.**
- Index bloat: dead tuples remain in indexes until vacuum runs
- Write amplification: HOT (Heap-Only Tuple) optimization in PostgreSQL avoids index updates when indexed columns don't change

**Staff signal.** MVCC's hidden cost is vacuum/GC — if it falls behind, table and index bloat degrades performance progressively. This is PostgreSQL's most common operational issue at scale.

## The Lost Update Problem

### Atomic Writes, Explicit Locking, and Compare-and-Set

**What.** A lost update occurs when two transactions both read a value, compute a new value based on it, and write back — the second write obliterates the first's change. Solutions: (1) Atomic operations (UPDATE counters SET val = val + 1) — the database handles the RMW atomically. (2) Explicit locking (SELECT ... FOR UPDATE) — the application locks the row during the read phase. (3) Compare-and-set (UPDATE ... WHERE val = old_val) — the write fails if the value changed since reading.

**Use when.** Counter increments, balance transfers, any read-modify-write pattern.

**Advantages.**
- Atomic ops: zero application complexity, database handles concurrency
- Explicit locks: flexible — application can perform arbitrary computation between read and write
- CAS: works even without explicit transactions (useful in leaderless/multi-leader)

**Tradeoffs.**
- Atomic ops: limited to expressions the database can evaluate (can't do arbitrary logic)
- Explicit locks: deadlock-prone if lock ordering isn't enforced; reduces concurrency
- CAS: fails under snapshot isolation if the database reads from the snapshot rather than current value
- Automatic detection (PostgreSQL SI): the database detects lost updates and aborts one transaction — elegant but not universal

**Staff signal.** Compare-and-set is broken on databases that evaluate the WHERE clause against a snapshot rather than current committed state — know which your database does.

## Write Skew and Phantoms

### Write Skew

**What.** Two transactions each read a set of rows satisfying some condition, check a constraint, and make a write that doesn't conflict row-by-row but together violates the constraint. Example: two doctors both check "at least one doctor on call," both see two on-call doctors, both remove themselves — now zero doctors are on call.

**Use when.** Any check-then-act pattern where the check involves multiple rows and the act is a write that could invalidate the check.

**Advantages.**
- Recognizing write skew is the key to knowing when snapshot isolation is insufficient

**Tradeoffs.**
- Not prevented by row-level locks (the conflicting transactions write to different rows)
- Not detected by automatic lost-update detection (different rows are written)
- Requires serializable isolation or application-level mitigation (materializing conflicts)

**Staff signal.** Write skew is the reason snapshot isolation is not serializable — it's the gap between them. If you can explain write skew clearly with an example, you demonstrate genuine understanding of isolation levels.

### Phantoms and Materializing Conflicts

**What.** A phantom occurs when one transaction's write changes the set of rows that another transaction's query would match. In write skew, the phantom is often the absence of a row that would prevent the violation. Materializing conflicts: artificially creating rows that can be locked to prevent the phantom (e.g., pre-creating all time-slot rows in a booking system so they can be locked).

**Use when.** You need to prevent write skew without full serializability and can identify the conflicting "phantom" set.

**Advantages.**
- Materializing conflicts converts a phantom problem into a simple locking problem
- Avoids the overhead of full serializability for specific known patterns

**Tradeoffs.**
- Leaks concurrency concerns into the data model — ugly and error-prone
- Not generalizable — each constraint needs its own materialized conflict table
- Last resort; prefer serializability if performance permits

**Staff signal.** Materializing conflicts is the "hack" that proves you need serializability — if you find yourself doing it in multiple places, you should switch isolation levels.

## Serializability Implementations

### Actual Serial Execution

**What.** Execute all transactions sequentially on a single thread, eliminating concurrency entirely. VoltDB and Redis (single-threaded command execution) use this approach.

**Use when.** Transactions are very fast (sub-millisecond), fit in memory, and throughput requirements can be met by a single core (or are partitionable across independent single-threaded partitions).

**Advantages.**
- Simplest possible concurrency model — no locks, no MVCC, no conflict detection
- Zero overhead from concurrency control mechanisms

**Tradeoffs.**
- Throughput limited to one CPU core per partition (≈100K-500K simple txns/sec)
- Interactive multi-round-trip transactions are unusable — all logic must be submitted as a stored procedure
- A single slow transaction blocks everything behind it
- Cross-partition transactions require coordination, losing the single-thread benefit

**Staff signal.** This approach became viable when datasets fit in RAM (no disk I/O stalls) and transactions can be expressed as pre-compiled stored procedures — the key enablers are RAM prices and stored-procedure compilation (VoltDB's approach).

### Two-Phase Locking (2PL)

**What.** A transaction acquires locks (shared for reads, exclusive for writes) and never releases any lock until the transaction commits or aborts. Predicate locks cover sets of rows matching a condition; index-range locks are a practical approximation that locks a larger range (the indexed key range) to prevent phantoms.

**Use when.** You need true serializability and can tolerate the concurrency reduction from lock waiting.

**Advantages.**
- Provides actual serializable isolation — prevents all anomalies including write skew and phantoms
- Well-understood implementation with decades of optimization

**Tradeoffs.**
- Readers block writers and writers block readers — dramatically reduced concurrency vs MVCC
- Deadlocks are inevitable under contention; require detection and victim abort
- Predicate locks are expensive to check; index-range locks are coarser but more practical
- Performance degrades non-linearly under contention (lock convoy effects)

**Staff signal.** 2PL is "pessimistic" — it assumes conflicts will happen and prevents them preemptively. The cost is paid even when conflicts don't occur. For read-heavy workloads, this is wasteful; for write-heavy contended workloads, it's often necessary.

### Serializable Snapshot Isolation (SSI)

**What.** Transactions execute concurrently against snapshots (like regular SI), but the database tracks read sets and detects potential serialization violations at commit time. If a transaction's reads have become stale (another committed transaction modified the premises), it's aborted. Used by PostgreSQL (SERIALIZABLE level since 9.1) and FoundationDB.

**Use when.** You need serializable isolation but can't tolerate the blocking behavior of 2PL — especially under read-heavy or low-contention workloads.

**Advantages.**
- No blocking: readers never block writers and vice versa (optimistic execution)
- Under low contention, abort rate is minimal and performance approaches regular snapshot isolation
- Detects write skew and phantoms that SI misses

**Tradeoffs.**
- Under high contention, many transactions abort and retry — wasted work
- Must track read sets, which has memory overhead
- Abort rate can spike unpredictably during load bursts
- Retried transactions may abort again if contention persists

**Staff signal.** SSI is "optimistic" — it assumes conflicts are rare and detects them retroactively. The economic question is: is the wasted work of occasional aborts cheaper than the constant blocking cost of 2PL? For most web workloads (low contention, high read ratio), yes.

## Isolation-Level Anomaly Matrix

| Anomaly | Read Uncommitted | Read Committed | Snapshot Isolation | Serializable |
|---------|:---:|:---:|:---:|:---:|
| Dirty read | ✓ possible | ✗ prevented | ✗ prevented | ✗ prevented |
| Dirty write | ✗ prevented | ✗ prevented | ✗ prevented | ✗ prevented |
| Read skew (non-repeatable read) | ✓ possible | ✓ possible | ✗ prevented | ✗ prevented |
| Lost update | ✓ possible | ✓ possible | Sometimes prevented* | ✗ prevented |
| Write skew | ✓ possible | ✓ possible | ✓ possible | ✗ prevented |
| Phantom | ✓ possible | ✓ possible | ✓ possible | ✗ prevented |

*PostgreSQL's SI detects lost updates automatically; MySQL/Oracle's "repeatable read" does not always.

## Distributed Transactions

### Two-Phase Commit (2PC)

**What.** A protocol for atomic commit across multiple nodes: Phase 1 (prepare) — coordinator asks all participants if they can commit; each responds yes/no. Phase 2 (commit/abort) — if all said yes, coordinator tells all to commit; if any said no, all abort.

**Use when.** You need atomicity across partitions or services and can tolerate the latency and availability costs.

**Advantages.**
- Guarantees all-or-nothing across distributed participants
- Well-understood protocol with wide implementation (XA, database-internal)

**Tradeoffs.**
- Blocking: if the coordinator crashes after prepare but before commit, participants are stuck holding locks indefinitely ("in-doubt" transactions)
- Availability: any single participant failure causes abort; coordinator failure causes blocking
- Latency: two network round-trips minimum; locks held across both phases

**Staff signal.** 2PC's fatal flaw is the in-doubt state: a participant that voted "yes" in prepare cannot unilaterally abort or commit — it must wait for the coordinator. If the coordinator is permanently lost, manual intervention is required. This makes 2PC unsuitable for systems that require high availability.

### Three-Phase Commit

**What.** An extension of 2PC that adds a "pre-commit" phase to avoid indefinite blocking. In theory, allows participants to reach a decision even if the coordinator fails.

**Use when.** Almost never in practice — the assumptions it requires (bounded network delay, no network partitions) don't hold in real systems.

**Tradeoffs.**
- Assumes synchronous network and bounded message delivery — violated in practice
- Additional round-trip latency without practical improvement in real-world failure scenarios
- Not implemented by any mainstream database

**Staff signal.** Know that 3PC exists, know it's meant to solve the blocking problem, and know why it fails in practice (asynchronous networks with unbounded delay violate its assumptions).

### XA Transactions

**What.** A standard interface (X/Open XA) for coordinating distributed transactions across heterogeneous resources (databases, message queues). The application server acts as the transaction coordinator.

**Use when.** Legacy enterprise systems needing atomic operations across multiple databases or a database and a message queue.

**Advantages.**
- Vendor-neutral standard supported by most enterprise databases and message brokers

**Tradeoffs.**
- All problems of 2PC plus: coordinator state must be durable (otherwise in-doubt on coordinator crash); locks held across systems for the entire transaction duration; operationally painful (orphaned prepared transactions require manual resolution)
- Performance: round-trip to all participants during prepare; lock duration spans network latency
- Operational: database administrators must manually resolve in-doubt transactions after coordinator failures

**Staff signal.** XA's operational reputation is poor — "in-doubt" transactions that hold locks for hours/days until manual resolution are a common production incident in enterprises. This is why microservices architectures reject XA in favor of sagas.

## Sagas and Event Patterns

### Saga Pattern

**What.** A long-lived distributed transaction decomposed into a sequence of local transactions, each with a compensating transaction that undoes its effect if a later step fails. Choreography: each service listens for events and acts. Orchestration: a central coordinator tells each service what to do.

**Use when.** Microservices coordination where distributed locking (2PC/XA) is unacceptable for availability or latency reasons.

**Advantages.**
- No distributed locks — each local transaction commits independently
- Services remain autonomous; no blocking on remote participants
- Works across heterogeneous systems that can't participate in 2PC

**Tradeoffs.**
- No isolation: intermediate states are visible to concurrent transactions
- Compensating transactions are hard to write correctly (how do you "un-send" an email?)
- Choreography: hard to understand overall flow; no single place to see saga state. Orchestration: coordinator is a single point of failure and complexity
- Semantic locks: holding a resource "reserved but not committed" pollutes the data model

**Staff signal.** Sagas sacrifice isolation — they provide atomicity (via compensation) and durability (each step commits locally) but explicitly give up the "I" in ACID. Application code must handle the anomalies that arise from seeing intermediate saga state.

### Outbox Pattern and Dual-Write Problem

**What.** The dual-write problem: writing to a database and publishing an event are two separate operations that can fail independently (database commits but event publish fails, or vice versa). The outbox pattern solves this: write the event to an "outbox" table in the same database transaction as the data change; a separate process tails the outbox and publishes events.

**Use when.** Any event-driven system that needs reliable event publishing without distributed transactions between the database and the message broker.

**Advantages.**
- Atomicity between data change and event: both are in one local transaction
- Exactly-once publishing (with idempotent consumers) despite process crashes
- Works with any database that supports transactions

**Tradeoffs.**
- Additional infrastructure: outbox poller/CDC connector (Debezium) must be operated
- Eventual delivery: events are published asynchronously after commit, not synchronously
- Outbox table grows continuously and requires cleanup/archival

**Staff signal.** The outbox pattern is the standard replacement for XA between a database and a message broker — it trades synchronous guarantee for operational simplicity and availability. CDC (log tailing) is even better than polling because it's already built into the database's replication infrastructure.

### Idempotency Keys and Exactly-Once Effects

**What.** A client-generated unique token (UUID) attached to each request. The server records processed tokens; duplicate requests with the same token return the cached result without re-executing. This makes retries safe.

**Use when.** Any API where network failures may cause duplicate delivery (payment processing, order creation, message sending).

**Advantages.**
- Retries become unconditionally safe — no duplicate charges, orders, or messages
- Decouples the client's retry logic from the server's state management

**Tradeoffs.**
- Server must store processed tokens (space cost; needs TTL-based cleanup)
- Token generation is the client's responsibility — broken clients can reuse tokens incorrectly
- The server must make the idempotency check and the operation atomic (otherwise a crash between check and execution causes inconsistency)

**Staff signal.** Idempotency keys are how you achieve exactly-once semantics in a system built on at-least-once delivery. The key insight: you're not preventing duplicate delivery, you're preventing duplicate effect.

### Long-Lived Transactions

**What.** Transactions that span minutes, hours, or days — interactive workflows, batch jobs, or human-in-the-loop processes that hold database resources for extended periods.

**Use when.** Understanding why they're an anti-pattern that must be refactored into sagas or shorter transactions.

**Tradeoffs.**
- Hold locks for their entire duration — blocking other transactions and causing widespread contention
- Increase MVCC bloat (long-running snapshots prevent vacuum/GC of old versions)
- Higher abort probability (more time = more chances for conflict or timeout)
- In PostgreSQL, long transactions prevent vacuum from reclaiming dead tuples, causing table bloat

**Staff signal.** Long-lived transactions are almost always a design error. The fix is to decompose into multiple short transactions (saga pattern) or use optimistic concurrency (read, compute offline, then commit with CAS). Never hold a database transaction open while waiting for human input.

## Common interview traps

- Claiming "serializable" isolation level provides linearizability — it doesn't; serializability is about transaction ordering, not real-time recency.
- Calling Oracle's "SERIALIZABLE" actually serializable — it's snapshot isolation with additional checking, not true serializability.
- Assuming 2PC is the same as 2PL — completely different concepts (atomic commit protocol vs locking strategy).
- Forgetting that sagas have no isolation — intermediate states are visible, which can cause application-level anomalies.
- Using "exactly-once delivery" when you mean "exactly-once processing" — delivery is at-least-once; idempotency gives you exactly-once effect.
- Proposing read committed as sufficient for a bank transfer — it permits lost updates on concurrent balance modifications.
- Thinking compare-and-set always works — it doesn't under snapshot isolation if the WHERE evaluates against the snapshot.
- Assuming aborted transactions have no cost — they've consumed locks, I/O, and CPU; under SSI, high abort rates indicate you need 2PL or redesign.

## Drill questions

1. Two users simultaneously book the last seat on a flight. Walk through how this plays out under read committed, snapshot isolation, and serializable isolation.
2. A transaction succeeds on the server but the client never receives the acknowledgment. What happens on retry without an idempotency key? With one?
3. You have a saga with steps A → B → C. Step C fails. Write the compensating transactions and explain what anomalies concurrent readers might observe.
4. Your PostgreSQL database uses SERIALIZABLE (SSI). Under what workload characteristics would you expect the abort rate to exceed 20%? How would you redesign?
5. Explain why the outbox pattern is preferred over application-level dual-write for publishing events. Give a specific failure scenario where dual-write corrupts consistency.
6. Two doctors check the on-call roster and both remove themselves. Under snapshot isolation, why isn't this detected as a conflict? What isolation level prevents it?
7. A 2PC coordinator crashes after sending "prepare" but before sending "commit." Describe the state of each participant and the operational recovery process.
8. When would you choose actual serial execution over 2PL? What constraints must your workload satisfy?
9. Compare the performance characteristics of 2PL and SSI for: (a) a read-heavy, low-contention workload; (b) a write-heavy, high-contention workload.
10. Explain materializing conflicts with a concrete example (meeting room booking). Why is it a design smell, and what's the cleaner alternative?
11. Your system processes payments. A network partition causes the idempotency key store to become temporarily unavailable. What do you do — reject the payment or process it risking duplicates?
