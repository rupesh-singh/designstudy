# 8. Consistency Models & Consensus

Consistency models define what guarantees a distributed system offers to its clients about the order and visibility of operations. Consensus — the ability of multiple nodes to agree on a value — underpins the strongest of these guarantees. Understanding the spectrum from eventual to linearizable, and knowing precisely where each model sits, is essential for making principled decisions about availability, latency, and correctness.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Eventual consistency | Replicas converge sometime, no timing guarantee | High availability with tolerance for stale reads |
| Linearizability | Operations appear atomic and instantaneous; recency guarantee | Leader election, unique constraints, coordination |
| Sequential consistency | All nodes see the same total order, but not necessarily real-time | Memory models, less costly than linearizability |
| Causal consistency | Operations ordered only by causality; concurrent ops unordered | Availability under partitions with meaningful ordering |
| Session guarantees | Per-client ordering promises (read-your-writes, monotonic reads) | User-facing applications needing intuitive behavior |
| CAP / PACELC | Impossibility constraints on consistency + availability + partitions | Architecture-level decision-making |
| Total order broadcast | Reliable delivery of messages in the same order to all nodes | Replicated state machines, consensus equivalence |
| Consensus (Paxos/Raft) | Nodes agree on a sequence of values despite failures | Leader election, atomic commit, log replication |
| FLP impossibility | No deterministic async consensus protocol can guarantee termination | Understanding why consensus protocols use timeouts |
| Two-phase commit | Atomic commit across participants; blocks on coordinator failure | Distributed transactions (with awareness of its fragility) |
| ZooKeeper/etcd | Coordination kernel: linearizable CAS, ephemeral nodes, watches | Config management, leader election, distributed locks |
| Fencing + distributed locks | Correctness of mutual exclusion despite pauses and partitions | Protecting shared mutable state |
| CRDTs / CALM | Coordination-free convergent data structures | High availability without consensus overhead |

## The Consistency Spectrum

### Linearizability
**What.** A system is linearizable if every operation appears to take effect at a single atomic instant between its invocation and response, and all operations form a total order consistent with real time. Informally: the system behaves as if there is only one copy of the data, and every read returns the most recent completed write.
**Use when.** Leader election (must see the latest leader), uniqueness constraints (only one user gets a username), any situation where stale reads cause correctness violations.
**Advantages.**
- Simplest mental model for clients: the system appears as a single-threaded data store
- Eliminates "read after write" anomalies and stale-read-based race conditions
**Tradeoffs.**
- Requires coordination (typically consensus or synchronous replication), adding latency
- Unavailable during network partitions (if choosing consistency over availability)
- Performance cost: every read may need to contact a quorum or the leader
**Staff signal.** Linearizability and serializability are orthogonal concepts. Serializability is about transaction isolation (equivalent to some serial ordering). Linearizability is about recency of individual operations with respect to real time. Strict serializability is the combination: transactions appear serial AND respect real-time ordering.

### Sequential Consistency
**What.** All operations appear to execute in some total order, and each client's operations appear in program order within that sequence — but there is no requirement that this order corresponds to real-time wall-clock ordering. Two clients issuing operations concurrently may see them ordered differently than an external observer would expect.
**Use when.** Hardware memory models (many CPUs provide sequential consistency or variants); scenarios where you need a global order but not real-time recency.
**Advantages.**
- Weaker than linearizability, so potentially cheaper to implement
- Still provides a single agreed-upon history
**Tradeoffs.**
- Does not guarantee you read the "latest" value — only that all nodes agree on some consistent ordering
- Rarely offered as an explicit choice in distributed databases (it is more common in CPU memory models)
**Staff signal.** The crucial difference from linearizability: sequential consistency allows a read to return a "stale" value as long as all observers agree on the same ordering. Linearizability additionally demands that the ordering respects real-time precedence.

### Causal Consistency and Causal+
**What.** Causally related operations must be seen in the same order by all nodes; concurrent operations (not causally linked) may be seen in different orders by different nodes. Causal+ adds convergence: concurrent operations must eventually be resolved identically everywhere (typically via deterministic merge functions).
**Use when.** You need meaningful ordering guarantees while remaining available during partitions — causal consistency is the strongest model achievable without sacrificing availability.
**Advantages.**
- Available under network partitions (does not require synchronous coordination)
- Preserves intuitive "if I saw X then I should see X's effects" semantics
- Lower latency than linearizability since it requires no cross-partition round-trips for unrelated operations
**Tradeoffs.**
- Tracking causality requires metadata (vector clocks or explicit dependency graphs)
- Does not prevent all anomalies: concurrent conflicting writes are still possible
- Implementation complexity: must propagate causal dependencies with every operation
**Staff signal.** Causal consistency sits at the exact boundary defined by the CALM theorem: it is the strongest consistency level achievable with coordination-freedom. Going stronger (to linearizable) necessarily requires coordination and sacrifices availability under partitions.

### Eventual Consistency
**What.** If no new updates are made, all replicas will eventually converge to the same value. No guarantee about when convergence occurs, what intermediate states are visible, or how conflicts are resolved.
**Use when.** Maximizing availability and latency when stale reads are tolerable and the application can handle temporary divergence (DNS, CDN caches, social media feeds).
**Advantages.**
- Always available, always writable, minimal coordination overhead
- Scales linearly with replicas for read throughput
**Tradeoffs.**
- "Eventually" is undefined — could be milliseconds or hours
- Clients may observe non-monotonic reads, read-after-write violations, and causal anomalies
- Conflict resolution must be handled somehow (LWW, merge functions, manual)
**Staff signal.** Eventual consistency is not a single model but a family: the guarantees vary enormously depending on the conflict resolution strategy. Saying "we use eventual consistency" without specifying conflict resolution is an incomplete design.

### Session Guarantees
**What.** Per-client promises layered atop weaker base consistency: (1) Read-your-writes: a client always sees its own writes. (2) Monotonic reads: a client never sees state go backward. (3) Monotonic writes: a client's writes are applied in issue order. (4) Writes-follow-reads: a write is ordered after any write the client has previously observed.
**Use when.** User-facing applications where the full cost of linearizability is too high but "refresh the page and your post disappears" is unacceptable.
**Advantages.**
- Intuitive UX without global coordination
- Can be implemented by session-sticky routing or by tracking client read/write versions
**Tradeoffs.**
- Sticky sessions reduce load balancer flexibility and complicate failover
- Version-tracking approaches add metadata overhead to every request
**Staff signal.** Session guarantees are often what product teams actually need when they say "strong consistency" — they mean a single user's experience should be coherent, not that all users globally see the same state simultaneously.

## CAP, PACELC, and the Cost of Linearizability

### CAP Theorem Stated Precisely
**What.** In the presence of a network partition (P), a distributed system must choose between consistency (C — linearizability specifically, not generic "consistency") and availability (A — every non-failed node can process requests). When there is no partition, you can have both. CAP does not say "pick two of three" — partitions are not optional; they will occur.
**Use when.** Making architectural trade-off decisions between CP and AP behavior; communicating with stakeholders about unavoidable trade-offs.
**Advantages.**
- Provides a clear impossibility boundary for system design
**Tradeoffs.**
- Wildly over-simplified: most decisions are about latency, not binary partition/no-partition
- "C" in CAP means only linearizability — weaker models like causal are available under partitions
- Partitions are rare in modern datacenters; PACELC better captures the latency trade-off during normal operation
**Staff signal.** The most common misstatement: "CAP says choose two of three." Correct statement: during a partition, you must choose between linearizability and availability. The real design question is what you do during normal (partition-free) operation — this is what PACELC captures with its "else latency vs consistency" clause.

### PACELC
**What.** Extension of CAP: if Partition occurs, choose Availability or Consistency; Else (normal operation), choose Latency or Consistency. This captures why systems like DynamoDB (PA/EL) and Spanner (PC/EC) behave differently even when no partition exists.
**Use when.** Explaining why Cassandra (PA/EL) is fast but eventually consistent, while Spanner (PC/EC) is slower but linearizable, even absent partitions.
**Advantages.**
- Captures the latency dimension that CAP ignores
- Better classification of real systems' behavior
**Tradeoffs.**
- Still a simplification; real systems have tunable consistency per operation
**Staff signal.** PACELC reveals that the more common trade-off engineers face is not "partition behavior" but "how much latency am I willing to pay for stronger consistency during normal operation."

## Ordering and Consensus

### Total Order Broadcast / Atomic Broadcast
**What.** A protocol that delivers messages to all nodes in the same order, with no gaps. If node A delivers message M before M', then every node delivers M before M'. Equivalent in power to consensus: given one, you can build the other.
**Use when.** Replicated state machines, replicated logs, maintaining identical state across replicas.
**Advantages.**
- Foundation for consistent replication: apply the same operations in the same order → same state
- Exactly equivalent to consensus — any solution to one solves the other
**Tradeoffs.**
- Requires a consensus protocol underneath (Raft, Paxos, etc.)
- Throughput limited by consensus latency per message/batch
**Staff signal.** The equivalence between total order broadcast and consensus is the key theoretical insight: implementing a linearizable register requires consensus, and consensus can be built atop total order broadcast. This is why you cannot have linearizability without coordination.

### Consensus: Problem Statement and FLP
**What.** Consensus requires nodes to agree on a single value satisfying: (1) Uniform agreement — no two nodes decide differently. (2) Integrity — a node decides at most once. (3) Validity — the decided value was proposed by some node. (4) Termination — every non-failed node eventually decides. The FLP impossibility result proves no deterministic algorithm can guarantee all four in an asynchronous system with even one possible crash.
**Use when.** Understanding why consensus protocols (Raft, Paxos) use timeouts and leader election — they circumvent FLP by introducing partial synchrony assumptions.
**Advantages.**
- FLP tells you what is provably impossible, preventing wasted effort on impossible designs
**Tradeoffs.**
- FLP does not mean consensus is impossible in practice — it means deterministic termination cannot be guaranteed; randomized and timeout-based protocols work in practice
**Staff signal.** FLP is an impossibility result about guaranteed termination in a purely asynchronous model. Real protocols (Raft, Paxos) use timeouts (partial synchrony assumption) to detect failures and make progress, sacrificing guaranteed termination for high-probability termination. Safety properties (agreement, integrity) are never sacrificed.

### Two-Phase Commit (2PC)
**What.** A coordinator asks all participants to prepare; if all vote "yes," the coordinator commits; if any votes "no," it aborts. The critical flaw: if the coordinator crashes after sending "prepare" but before sending the decision, participants who voted "yes" are stuck — they cannot abort (coordinator may have committed elsewhere) or commit (coordinator may have aborted elsewhere). They must wait indefinitely.
**Use when.** Distributed transactions across heterogeneous systems (XA); understanding why it is avoided in modern systems.
**Advantages.**
- Simple protocol; widely implemented in database drivers and application servers
- Guarantees atomicity across participants when all goes well
**Tradeoffs.**
- Blocking: a coordinator crash can leave participants holding locks indefinitely
- Not fault-tolerant: coordinator is a SPOF; participants cannot independently recover
- High latency: two round-trips minimum plus lock-hold duration
**Staff signal.** 2PC is not a true consensus protocol because it has a single point of failure and blocks rather than making progress when that point fails. Three-phase commit (3PC) attempts to address this but is not safe under network partitions.

### Paxos and Raft
**What.** Paxos (single-decree) achieves consensus on one value through a propose/accept protocol using numbered ballots and majority quorums. Multi-Paxos chains single-decree instances with a stable leader for efficiency. Raft provides equivalent safety guarantees with a more understandable leader-centric design: leader election via randomized timeouts, log replication via AppendEntries, and safety via the election restriction (only candidates with the most up-to-date log can win).
**Use when.** Building any system requiring replicated state machines, leader election, or total order broadcast.
**Advantages.**
- Raft: understandable, well-specified, directly implementable; industry standard (etcd, CockroachDB)
- Paxos: theoretically minimal; flexible (leaderless variants exist)
**Tradeoffs.**
- Leader-based protocols have throughput bounded by the leader's capacity
- Leader failures cause unavailability for one election timeout period
- All require majority quorums, meaning 2f+1 nodes to tolerate f failures
**Staff signal.** The two-round structure shared by all consensus protocols: Round 1 establishes a leader/ballot with a quorum's permission. Round 2 replicates the decision to a quorum. This structure ensures that any two quorums overlap, preventing conflicting decisions.

### Epochs/Terms and Quorum Intersection
**What.** Every consensus protocol uses monotonically-increasing epoch numbers (Raft terms, Paxos ballot numbers, Zab epoch IDs). A leader is valid only for its epoch. Quorum intersection (any two majority quorums share at least one member) ensures that a new leader always contacts at least one node that participated in the previous epoch's decisions, preventing data loss.
**Use when.** Explaining why majority quorums are the minimum; why split-brain cannot occur with correct quorum configuration.
**Advantages.**
- Mathematical guarantee against conflicting decisions: no two leaders in the same epoch, and any new leader learns all committed decisions
**Tradeoffs.**
- Requires 2f+1 nodes; minority partitions become unavailable
- Quorum size limits geographic distribution (latency to reach majority)
**Staff signal.** The quorum intersection property is the fundamental reason 2f+1 works: any two majorities of a set of 2f+1 nodes overlap in at least one node. This one node is the "bridge" that carries committed state from old leader to new leader.

### Leader Leases and Why Leaders Need Fencing
**What.** A leader lease lets the leader serve reads locally without contacting followers, improving read latency. The danger: if the leader is partitioned but its lease has not expired from its local perspective (clock skew, GC pause), it may serve stale reads while a new leader is already active.
**Use when.** Optimizing read latency in consensus-based systems; understanding the stale-read risk.
**Advantages.**
- Dramatically reduces read latency (local read, no quorum contact)
**Tradeoffs.**
- Safety depends on clock correctness or bounded clock skew
- A paused leader with an expired lease (from others' perspective) still believes it is valid
**Staff signal.** This is why etcd and CockroachDB implement lease-based reads carefully: the lease must be tied to the consensus epoch, and followers must refuse operations from old-epoch leaders (fencing).

## Coordination Services and Distributed Locks

### ZooKeeper, etcd, Consul
**What.** Coordination services that provide a small set of linearizable primitives: compare-and-set (CAS), ephemeral nodes (auto-deleted on session loss), sequential nodes (monotonic ordering), and watches/notifications. They run consensus internally (Zab for ZooKeeper, Raft for etcd/Consul) so that applications don't implement consensus themselves.
**Use when.** Leader election, distributed locks, service discovery, configuration management, partition assignment (Kafka uses ZooKeeper/KRaft for controller election).
**Advantages.**
- Battle-tested consensus under the hood; applications get linearizable semantics via simple APIs
- Ephemeral nodes solve the "detect dead lock-holder" problem naturally
**Tradeoffs.**
- Small data model — not a general-purpose database; designed for metadata, not bulk data
- The coordination service itself must be highly available (typically 3 or 5 nodes)
- Watches can be missed during disconnection; clients must re-read state on reconnect
**Staff signal.** The right mental model: these services are "consensus as a service" — they absorb the complexity of Paxos/Raft/Zab so your application doesn't need to. But they are a dependency: if ZooKeeper is down, every system depending on it for leader election is affected.

### Distributed Locks and the Redlock Debate
**What.** A correct distributed lock requires: (1) mutual exclusion — at most one holder at a time, (2) deadlock freedom — locks eventually become available, (3) fault tolerance — lock service survives node failures. The Redlock algorithm (Redis-based) attempts to achieve this using clock-based expiry across independent Redis nodes. The critique: without fencing tokens validated by the resource being protected, no timeout-based lock is safe against process pauses.
**Use when.** Deciding between a "best-effort" lock (Redis, for efficiency/deduplication) vs a "correctness" lock (ZooKeeper with fencing, for safety-critical mutual exclusion).
**Advantages.**
- Redis-based locks: very fast, simple deployment, sufficient for efficiency-oriented locking
- ZooKeeper-based locks: correct under arbitrary pauses when combined with fencing tokens
**Tradeoffs.**
- Redlock's safety depends on timing assumptions that fail under GC pauses, clock skew
- Correct fencing-token-based locks require the protected resource to cooperate (validate tokens)
**Staff signal.** The distinction to make in interviews: if the lock is for efficiency (avoiding duplicate work, reducing load), a Redis lock is fine — the worst case is occasional duplicate work. If the lock is for correctness (preventing data corruption), you need consensus-backed locks with fencing tokens checked by the downstream storage.

## Coordination Avoidance

### CALM Theorem and CRDTs
**What.** The CALM theorem (Consistency As Logical Monotonicity) states that computations whose outcomes are monotonically-determined (adding information never retracts previous conclusions) can be implemented without coordination. CRDTs (Conflict-free Replicated Data Types) are data structures designed so that concurrent operations always commute, converging without coordination — examples include G-Counters, OR-Sets, and LWW-Registers.
**Use when.** Building highly-available systems that need convergence without consensus: collaborative editing, distributed counters, shopping carts.
**Advantages.**
- Always available, always writable, convergence guaranteed by mathematical structure
- No coordination latency; operations apply locally and propagate asynchronously
**Tradeoffs.**
- Limited expressiveness: not all problems can be decomposed into monotonic/commutative operations
- Some CRDTs grow unboundedly (tombstones in OR-Sets); garbage collection requires coordination
- Semantics can be surprising (add-wins vs remove-wins for sets)
**Staff signal.** CRDTs are not a replacement for consensus — they are an alternative for specific data structures where the semantics naturally commute. The design challenge is reformulating your problem into one where commutativity holds.

### Byzantine Fault Tolerant Consensus (Brief)
**What.** PBFT (Practical Byzantine Fault Tolerance) achieves consensus with up to f < n/3 Byzantine (arbitrarily-faulty) nodes using O(n²) message complexity per decision. Blockchain-style protocols (Nakamoto consensus) use proof-of-work or proof-of-stake for probabilistic consensus among untrusted parties at large scale, trading finality speed for openness.
**Use when.** Permissioned blockchains (PBFT-family), public blockchains (Nakamoto), systems where participants are mutually distrustful.
**Advantages.**
- Correctness despite actively malicious participants
- Blockchain: permissionless participation, censorship resistance
**Tradeoffs.**
- PBFT: O(n²) messages limit practical cluster size to ~20–100 nodes
- Blockchain: probabilistic finality (confirmation takes minutes); enormous energy/resource cost for proof-of-work
**Staff signal.** BFT consensus in datacenters is almost never warranted because you control all nodes. The exception is multi-organization consortia where no single party is trusted to run the coordination service honestly.

## Common interview traps

- Confusing linearizability (single-object recency) with serializability (multi-object transaction isolation). These are orthogonal; strict serializability is their intersection.
- Saying "CAP means pick two" — partitions happen; the choice is between C and A during a partition, not in general.
- Treating eventual consistency as a specific guarantee — without specifying conflict resolution, it promises almost nothing.
- Claiming causal consistency requires consensus — it does not; it is achievable without coordination (per CALM).
- Believing 2PC is a consensus protocol — it is not; it has a single coordinator that blocks the protocol if it fails.
- Stating that Raft guarantees availability — it guarantees safety always, but liveness (progress) only with a majority of nodes and eventual leader election.
- Forgetting that FLP is about deterministic protocols in pure async — practical protocols use randomization or timeouts to circumvent it.
- Confusing total order broadcast with reliable broadcast — reliable broadcast does not guarantee ordering.

## Drill questions

1. Explain the precise difference between linearizability and serializability. Give a scenario that is serializable but not linearizable, and vice versa.
2. Why is causal consistency the strongest model achievable without sacrificing availability under partitions? What formal result underpins this claim?
3. A system uses Raft for consensus. The leader is network-partitioned from the majority. Describe exactly what happens from both the leader's and the majority's perspective.
4. Why does two-phase commit block, and how does three-phase commit attempt to fix it? Why does 3PC still fail under network partitions?
5. You are designing a distributed username uniqueness check. Why are Lamport timestamps insufficient, and what mechanism is actually needed?
6. Explain how ZooKeeper ephemeral nodes provide a building block for leader election. What happens when the leader's session expires? What race conditions are possible?
7. A team proposes using Redlock for a mutex that protects financial transactions. Construct the specific failure scenario that makes this unsafe, and propose the fix.
8. Under PACELC, classify DynamoDB, Spanner, and PostgreSQL streaming replication. Justify each classification.
9. What is the quorum intersection property, and why does it make 2f+1 the minimum for tolerating f crash failures? What happens with 2f nodes?
10. Describe a scenario where a leader with a valid lease serves a stale read. How does Spanner's TrueTime approach prevent this?
11. When would you choose a CRDT over a consensus-based approach? Give a concrete example where a CRDT is ideal and one where it is fundamentally insufficient.
