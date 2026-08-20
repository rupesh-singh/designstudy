# 4. Replication

Replication keeps copies of the same data on multiple machines. The three independent motivations — reducing user-perceived latency by serving from a geographically close node, surviving machine or datacenter failures without downtime, and scaling read throughput horizontally — each drive different architectural choices. Most interview-level design errors come from conflating these goals or assuming one topology handles all three equally well.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Single-leader replication | One node accepts writes, followers serve reads | You need simple consistency with read-heavy workload |
| Sync vs async replication | Controls durability-latency dial | You must decide how much write latency you'll pay for guaranteed durability |
| Chain replication | Serializes writes through a chain for strong consistency | You want strong consistency without leader bottleneck on reads |
| New follower setup | Snapshot + log catch-up bootstraps a replica | Adding capacity or replacing failed nodes |
| Failover | Promote a follower when leader dies | Maintaining availability after leader failure |
| Statement-based replication | Replays SQL statements on followers | Simple but determinism problems disqualify it for most uses |
| WAL shipping | Ships physical storage-engine log bytes | Tight coupling to storage format; used by PostgreSQL streaming replication |
| Logical/row-based log | Ships decoded row-change events | Decouples replication from storage format; enables CDC |
| Trigger-based replication | Application-level hooks capture changes | When you need selective or cross-system replication |
| Read-after-write consistency | User always sees their own writes | Any user-facing app with read replicas |
| Monotonic reads | No time-travel backwards across reads | Preventing confusing UX when load-balancing across replicas |
| Consistent prefix reads | Causally ordered writes appear in order | Conversations, threads, or any causal chain |
| Multi-leader replication | Multiple nodes accept writes | Multi-datacenter, offline-first, or collaborative editing |
| Conflict resolution | Converging divergent writes | Any multi-writer topology |
| Leaderless (Dynamo-style) | Any node accepts reads/writes via quorums | High availability with tunable consistency |
| Sloppy quorum / hinted handoff | Writes proceed even when home nodes are down | Prioritizing write availability over strict quorum membership |
| Read repair / anti-entropy | Heals stale replicas | Eventually converging leaderless replicas |
| Version vectors | Detects concurrency vs causality between writes | Resolving conflicts correctly in multi-writer systems |

## Single-Leader Replication

### Why Replicate — and Why Goals Diverge

**What.** Replication serves three purposes: (1) latency reduction by placing data near users, (2) fault tolerance by surviving node/datacenter loss, and (3) read throughput scaling by spreading queries across replicas. Each goal can demand a different replication topology and consistency guarantee.

**Use when.** Every production system that cannot tolerate single-machine failure or single-region latency.

**Advantages.**
- Geographic proximity cuts round-trip times from hundreds of ms to single-digit ms
- N replicas tolerate N-1 failures (with appropriate failover)
- Read-heavy workloads (common in web apps) get near-linear read scaling

**Tradeoffs.**
- More replicas means more consistency complexity; writes must propagate
- Each goal pulls configuration differently: latency wants async + geo-distributed, durability wants sync, throughput wants many followers

**Staff signal.** Articulate that latency-motivated replication may actively conflict with durability-motivated replication (async is fast but can lose data), and that these tensions must be resolved per-use-case, not per-cluster.

### Single-Leader Model

**What.** One designated node (the leader/primary) accepts all writes; followers receive a replication stream and serve reads. This is the default model in PostgreSQL, MySQL, MongoDB, and Kafka partition leaders.

**Use when.** Workload is read-heavy and you want a simple mental model for consistency — all writes serialize through one node.

**Advantages.**
- No write conflicts by design — total order on writes at the leader
- Simple to reason about for application developers
- Followers can be added without changing write path

**Tradeoffs.**
- Leader is a write-throughput bottleneck (vertical scaling only for writes)
- Leader failure requires failover, introducing a window of unavailability or data loss
- All writes must traverse the network to the leader; geographic distance adds latency

**Staff signal.** Explain that single-leader's real constraint is not CPU but the sequential WAL flush — write throughput is bounded by fsync latency × concurrency, not just CPU.

### Synchronous vs Asynchronous vs Semi-Synchronous

**What.** Synchronous replication waits for follower acknowledgment before confirming a write to the client. Asynchronous confirms immediately after the leader persists. Semi-synchronous (e.g., MySQL semi-sync) waits for at least one follower, leaving the rest async.

**Use when.** You must explicitly decide where on the durability-latency spectrum each write sits.

**Advantages.**
- Sync: guarantees follower has the data — zero data loss on leader crash
- Async: minimal write latency — leader doesn't block on network
- Semi-sync: practical middle ground — one durable copy beyond leader

**Tradeoffs.**
- Sync: one slow or dead follower stalls all writes; unusable with many followers
- Async: leader crash loses all un-replicated writes; potential data loss window is the replication lag
- Semi-sync: still one synchronous round-trip; failover must promote the sync follower specifically

**Staff signal.** Know that "synchronous replication" in practice often means semi-synchronous (one sync follower + N async), because fully synchronous to all replicas is operationally untenable.

### Chain Replication

**What.** Nodes form a chain: writes enter at the head and propagate sequentially to the tail; reads are served only from the tail. The tail's acknowledgment confirms the write is on all nodes.

**Use when.** You need strong consistency with high read throughput and can tolerate head-of-chain as a write bottleneck (used in Azure Storage, HDFS variants).

**Advantages.**
- Reads at the tail are always consistent — no stale reads
- Write durability equals full replication without separate sync mechanism
- Read load doesn't hit the write path at all

**Tradeoffs.**
- Chain length equals write latency (each hop adds network RTT)
- Any mid-chain failure requires reconfiguration; more complex failure handling than leader-follower
- Write throughput limited by the slowest link in the chain

**Staff signal.** Chain replication separates the read and write endpoints entirely, which is its key advantage over leader-follower where reads from the leader compete with writes.

## Follower Lifecycle and Failover

### Setting Up New Followers

**What.** A new follower is bootstrapped by taking a consistent snapshot of the leader's data, copying it to the new node, then replaying all log entries from the snapshot's known position (LSN/binlog offset) forward until caught up.

**Use when.** Scaling read capacity, replacing a failed replica, or migrating to new hardware.

**Advantages.**
- No downtime or locking on the leader (snapshot is taken from a point-in-time, not a lock)
- Deterministic catch-up — the log position provides an exact resume point

**Tradeoffs.**
- Snapshot size determines bootstrap time (can be hours for terabyte-scale databases)
- Leader must retain logs from the snapshot point until follower catches up — log retention sizing matters

**Staff signal.** The critical detail is the snapshot must record its exact log position so the follower knows where to start replaying; without this, the catch-up is undefined.

### Follower Failure and Leader Failure (Failover)

**What.** A crashed follower recovers by replaying its local log from the last confirmed position. A crashed leader requires failover: detecting the failure, electing a new leader from followers, and reconfiguring clients/other followers to use it.

**Use when.** Any production deployment — failures are inevitable.

**Advantages.**
- Follower recovery is self-healing with no coordination needed
- Automatic failover can restore write availability in seconds (e.g., Patroni for PostgreSQL)

**Tradeoffs.**
- Failover hazards are severe: async followers may lag, so promoting one can lose committed writes
- Split brain: if the old leader isn't properly fenced, two nodes accept writes simultaneously
- Timeout tuning: too short causes spurious failovers under load spikes; too long prolongs outages

**Staff signal.** The most dangerous failover scenario is a promoted follower that discards writes the old leader had confirmed to clients (violating durability). GitHub's 2012 MySQL incident is the canonical example — a promoted replica diverged, causing data corruption that required manual intervention.

## Replication Log Implementations

### Statement-Based Replication

**What.** The leader logs every write statement (INSERT, UPDATE, DELETE) and sends it to followers for re-execution.

**Use when.** Rarely appropriate today; MySQL used this historically before row-based became default.

**Advantages.**
- Compact log — a single statement can represent millions of row changes

**Tradeoffs.**
- Non-deterministic functions (NOW(), RAND()) produce different results on followers
- Auto-incrementing columns, triggers, and side effects create divergence
- Statement ordering with concurrent transactions is fragile

**Staff signal.** Statement-based replication fails fundamentally with any non-determinism — it's not fixable by edge-case patching; logical replication is the structural solution.

### WAL Shipping

**What.** The leader sends its write-ahead log (the physical bytes that describe disk block changes) directly to followers, who apply identical block-level modifications. PostgreSQL streaming replication works this way.

**Use when.** You want byte-identical replicas and can tolerate tight version coupling.

**Advantages.**
- Zero ambiguity — followers are physically identical to leader at the block level
- No translation layer; replication is a byproduct of crash recovery infrastructure

**Tradeoffs.**
- Coupled to storage engine format — cannot replicate across different versions or engines
- Followers cannot run different indexes or schema; no logical decoupling
- Log volume can be high (every physical page write, not just logical changes)

**Staff signal.** WAL shipping prevents zero-downtime upgrades because leader and follower must run the same storage format version.

### Logical (Row-Based) Replication

**What.** A decoded stream of row-level changes (insert row X, delete row Y, update columns A,B of row Z) is shipped to followers. MySQL's row-based binlog and PostgreSQL's logical decoding both implement this.

**Use when.** You need change data capture (CDC), cross-version replication, or heterogeneous subscribers (data warehouses, search indexes, caches).

**Advantages.**
- Decoupled from storage engine — followers can use different versions, indexes, or even different databases
- Enables CDC pipelines (Debezium, Maxwell) for event-driven architectures
- Deterministic — no function evaluation ambiguity

**Tradeoffs.**
- Larger log volume than statement-based for bulk operations (one entry per row)
- Schema changes require careful coordination (DDL replication is separate)

**Staff signal.** Logical replication is the foundation of CDC, which is how modern systems avoid dual-write problems — a single source of truth (the database) emits a change stream that feeds downstream systems.

### Trigger-Based Replication

**What.** Application-level database triggers or stored procedures capture writes and funnel them into a replication channel. Oracle GoldenGate and Databus use variations of this approach.

**Use when.** You need to replicate a subset of data, transform it during replication, or bridge systems where built-in replication is insufficient.

**Advantages.**
- Maximum flexibility — custom filtering, transformation, and routing
- Can replicate across heterogeneous systems not designed to interoperate

**Tradeoffs.**
- Significant overhead — triggers fire in the write path, adding latency to every transaction
- Error-prone; bugs in trigger logic corrupt the replication stream
- Much harder to operate and debug than native replication

**Staff signal.** Trigger-based replication is a last resort, not a default — it's the "escape hatch" when native replication can't express your requirements.

## Replication Lag and Consistency Guarantees

### Read-After-Write Consistency

**What.** A guarantee that after a user performs a write, any subsequent read by that same user will reflect that write — even if the read hits a different replica.

**Use when.** Any user-facing application where stale reads after a write would confuse or frustrate the user (profile updates, message posting, settings changes).

**Advantages.**
- Users never see their own actions "disappear" — critical for perceived reliability

**Tradeoffs.**
- Implementation techniques all carry costs: routing user reads to leader (sacrifices read scaling), tracking write timestamps and comparing to replica lag (adds metadata overhead), or reading from leader for a brief window after writes (complex routing logic)

**Staff signal.** Cross-device read-after-write (e.g., write on phone, read on laptop) is significantly harder because you can't use client-local timestamps — you need centralized metadata about the user's most recent write timestamp.

### Monotonic Reads

**What.** Once a user has observed a value at some version, subsequent reads by that user will never return an older version. Prevents the illusion of "going back in time."

**Use when.** Reads are load-balanced across replicas with different lag; without this guarantee, refreshing a page might show older content.

**Advantages.**
- Simple mental model for users — data never regresses

**Tradeoffs.**
- Typically achieved by pinning a user to a single replica (consistent hashing on user ID), which limits load-balancing flexibility and creates hot replicas for active users

**Staff signal.** Monotonic reads is weaker than read-after-write; you can have monotonic reads while still missing your own most recent write (if you've never read it from this replica yet).

### Consistent Prefix Reads

**What.** If a sequence of writes occurs in a causal order (A happened before B), any reader will observe them in that same order — never B without A.

**Use when.** Conversational or causal data: replies must not appear before the messages they reply to; events must not appear out of logical sequence.

**Advantages.**
- Prevents paradoxical observation of effects before causes

**Tradeoffs.**
- In partitioned databases, cross-partition causal ordering requires coordination (e.g., logical timestamps) because partitions have no shared total order
- Single-partition writes naturally preserve this; it's the multi-partition case that's hard

**Staff signal.** Consistent prefix reads is automatically satisfied in single-leader, single-partition systems but requires explicit causal tracking in multi-partition or multi-leader setups.

## Multi-Leader Replication

### Multi-Leader Model and Use Cases

**What.** Multiple nodes independently accept writes, then asynchronously replicate changes to each other. Each leader is a full read-write node.

**Use when.** Multi-datacenter deployments (one leader per DC for local write latency), offline-first applications (each device is a "leader" that syncs later), or collaborative real-time editing.

**Advantages.**
- Write latency is local to the datacenter or device — no cross-region synchronous path
- Tolerates network partitions between datacenters; each DC continues independently
- Higher aggregate write throughput than single-leader

**Tradeoffs.**
- Write conflicts are inevitable and must be resolved
- Debugging is harder — the same data can be modified simultaneously in multiple places
- Autoincrementing keys, sequences, and triggers all become problematic

**Staff signal.** Multi-leader is rarely worthwhile for a single-datacenter deployment — the conflict resolution complexity isn't justified when network latency to a single leader is already low.

### Multi-Leader Topologies

**What.** Circular: each leader forwards to the next in a ring. Star: one central hub relays to all others. All-to-all: every leader sends to every other.

**Use when.** Choosing the communication pattern between leaders in a multi-leader cluster.

**Advantages.**
- All-to-all has no single point of failure and lowest propagation delay
- Star/circular are simpler to configure for small deployments

**Tradeoffs.**
- Circular and star have single points of failure — one node dying breaks propagation
- All-to-all can deliver messages out of causal order (different path lengths) — requires version vectors or logical timestamps to sort correctly

**Staff signal.** All-to-all with version vectors is the only production-viable topology for more than two leaders; circular and star are fragile enough to be effectively deprecated.

### Conflict Resolution

**What.** When the same record is modified on multiple leaders before replication converges, a conflict exists. The system must deterministically converge to one value across all replicas.

**Use when.** Any multi-leader or leaderless write topology — conflicts are a structural inevitability, not an edge case.

**Advantages.**
- Conflict avoidance (routing all writes for a key to one leader) eliminates the problem entirely when feasible
- Application-level merge functions can express domain-specific resolution (e.g., union for shopping carts)

**Tradeoffs.**
- Last-write-wins (LWW): simple but silently discards concurrent writes — data loss by design
- CRDTs: mathematically convergent but limited to specific data structures (counters, sets, registers)
- Operational transformation: complex, used in collaborative editors (Google Docs), hard to generalize

**Staff signal.** LWW is not a conflict resolution strategy — it's a conflict avoidance strategy that pretends conflicts don't exist by declaring one write the "winner" based on timestamps that may not even be comparable (clock skew). It is appropriate only when losing concurrent writes is acceptable (e.g., cache refresh).

## Leaderless Replication

### Dynamo-Style Quorums

**What.** Writes are sent to all N replicas; the write succeeds when W acknowledge. Reads query all N replicas; the read returns a result when R respond. The quorum condition w + r > n guarantees that read and write sets overlap, meaning at least one node has the latest value.

**Use when.** You prioritize availability over consistency (e.g., DynamoDB, Cassandra, Riak) and can tolerate occasional stale reads or conflict resolution.

**Advantages.**
- No leader = no single point of failure for writes
- Tunable consistency: adjusting w and r shifts the read/write latency balance
- Tolerates up to N-W write failures and N-R read failures

**Tradeoffs.**
- w + r > n does NOT guarantee linearizability — concurrent writes can still produce conflicts needing resolution
- Edge cases: sloppy quorums, read repair timing, and replica divergence can all violate expected freshness
- Higher read/write amplification (multiple nodes for every operation)

**Staff signal.** The quorum guarantee is purely about freshness overlap, not ordering. Two concurrent writes satisfying w + r > n can still produce conflicting values that require version vectors to detect and resolve.

### Sloppy Quorums and Hinted Handoff

**What.** When the designated N home nodes for a key are not all reachable, writes can temporarily go to other nodes (sloppy quorum). Those temporary nodes hold the data as "hints" and forward it to the rightful owners once they recover (hinted handoff).

**Use when.** You need writes to succeed even during partial network failures (Riak, Cassandra with appropriate settings).

**Advantages.**
- Write availability during network partitions — data isn't refused
- Self-healing: hinted handoff automatically repairs once connectivity returns

**Tradeoffs.**
- Sloppy quorum voids the w + r > n freshness guarantee — reads might miss recent writes held on non-home nodes
- Hints can accumulate during extended outages, causing burst replication on recovery

**Staff signal.** A sloppy quorum is no longer a quorum in the formal sense — it's a durability mechanism, not a consistency mechanism. Distinguish them clearly in an interview.

### Read Repair and Anti-Entropy

**What.** Read repair: when a read detects a stale replica (by comparing version numbers from multiple responses), the coordinator writes the fresh value back to the stale node. Anti-entropy: a background process continuously compares replicas (using Merkle trees for efficient diff) and synchronizes divergent data.

**Use when.** Leaderless systems need convergence mechanisms because there's no replication stream from a leader.

**Advantages.**
- Read repair heals the most-accessed data automatically (hot paths stay fresh)
- Merkle-tree anti-entropy efficiently identifies divergent key ranges without full data comparison

**Tradeoffs.**
- Read repair only fixes data that's actively read — cold data may remain stale indefinitely without anti-entropy
- Anti-entropy is background and eventually consistent — it doesn't provide real-time repair

**Staff signal.** Without anti-entropy, rarely-read data in a leaderless system can remain stale permanently — read repair alone is insufficient for full convergence.

### Version Vectors vs Vector Clocks

**What.** Both track causality across distributed nodes. A vector clock has one entry per process/actor tracking events in that process. A version vector has one entry per replica tracking write versions to a specific data item. Version vectors are per-key; vector clocks are per-process.

**Use when.** Detecting concurrent writes (neither causally ordered) in leaderless/multi-leader systems to trigger conflict resolution.

**Advantages.**
- Correctly distinguishes "one write happened before another" from "two writes are concurrent"
- Enables precise conflict detection without false positives

**Tradeoffs.**
- Vector size grows with number of replicas/actors — metadata overhead per key
- Garbage collection of old entries requires coordination

**Staff signal.** The distinction: vector clocks track process event counts (Lamport-style, per actor), while version vectors track data item version counts (per replica, per key). Dynamo-style systems use version vectors. Many sources incorrectly call them "vector clocks."

### Replication Factor Selection

**What.** The choice of N (number of replicas) determines storage cost (N× data size), write amplification (every write goes to N nodes), and fault tolerance (can lose N-1 replicas for reads, N-W for writes).

**Use when.** Designing any replicated system — the replication factor is a fundamental capacity and reliability parameter.

**Advantages.**
- Higher N increases durability (lower probability of all copies lost) and read availability
- Enables more flexible quorum configurations (larger N allows more w/r combinations)

**Tradeoffs.**
- Storage cost scales linearly with N
- Write latency and throughput inversely affected (more nodes to confirm)
- Operational complexity: more nodes to patch, monitor, and rebalance

**Staff signal.** N=3 is the industry default (tolerates one failure while maintaining a quorum of 2), but the real question is whether the third copy should be in the same rack, same AZ, or a different region — this determines what failure domains you survive.

## Common interview traps

- Confusing "synchronous replication" with "all replicas are sync" — in practice it means one sync follower (semi-sync).
- Claiming w + r > n provides linearizability — it only guarantees read-write overlap, not ordering.
- Forgetting that sloppy quorums destroy the quorum guarantee entirely.
- Treating LWW as a valid conflict resolution for data that matters — it is silent data loss.
- Confusing vector clocks with version vectors — they are structurally similar but semantically different.
- Assuming automatic failover is strictly better than manual — spurious failovers under load cause more outages than they prevent.
- Neglecting the split-brain scenario: two leaders accepting writes simultaneously corrupts data permanently.
- Assuming read-after-write consistency is the default — it is not; it requires explicit implementation effort.

## Drill questions

1. You have a single-leader setup with one sync and two async followers. The sync follower dies. What are your options, and what does each sacrifice?
2. Why can't you just use `NOW()` in statement-based replication? Walk through a concrete scenario where it breaks.
3. A user writes a comment, then immediately refreshes and doesn't see it. Diagnose the possible causes and propose three distinct fixes.
4. Under what conditions would you choose multi-leader over single-leader for a system that operates in one region?
5. Two users concurrently edit the same document in a multi-leader setup. Walk through conflict detection and resolution using version vectors.
6. Why is read repair insufficient as the sole anti-entropy mechanism? What goes wrong operationally?
7. You're designing a leaderless system with N=5. What w and r values would you choose for a read-heavy workload that tolerates occasional staleness? What about a write that must not be lost?
8. Explain why promoting an async follower during failover can violate durability guarantees that were already acknowledged to the client.
9. When would chain replication be preferred over standard leader-follower? What failure mode does it handle better, and what does it handle worse?
10. A system uses sloppy quorums and hinted handoff. A network partition heals after 30 minutes. Describe the burst of activity that follows and its operational risks.
