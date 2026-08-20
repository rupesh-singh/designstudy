# 7. Distributed System Faults, Networks & Time

Distributed systems are defined by partial failure: some components can malfunction while others continue operating, and there is no shared global state that tells you which is which. Mastering this topic means understanding that every network message, every clock reading, and every node's liveness assertion comes with inherent uncertainty — and designing protocols that remain correct despite that uncertainty.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Partial failure | Any subset of components can fail independently | Designing any multi-node system |
| Unreliable networks | Messages may be lost, delayed, duplicated, or reordered | Choosing timeouts, designing RPCs |
| Network partitions | Subset of nodes cannot communicate with another subset | Evaluating consistency vs availability |
| Timeouts & failure detection | Distinguish crashed nodes from slow ones (imperfectly) | Building leader election, health checks |
| Synchronous vs async model | Bounds (or lack thereof) on delay and clock drift | Choosing system model for proofs |
| Safety vs liveness | Correctness decomposition into "nothing bad" vs "something good eventually" | Reasoning about protocol guarantees |
| Physical clocks (NTP) | Wall-clock time with bounded but non-zero error | Timestamps for humans, TTL expiry |
| Logical clocks (Lamport) | Total ordering of events respecting causality | Ordering events without physical time |
| Vector clocks | Detecting concurrent vs causally-ordered events | Conflict detection in replicated data |
| Hybrid logical clocks | Physical time augmented with logical counters | CockroachDB-style causal ordering |
| TrueTime / confidence intervals | Bounded clock uncertainty with explicit error bars | Spanner's external consistency |
| Process pauses | Any thread can stall for unbounded time (GC, VM migration) | Designing leases, lock safety |
| Fencing tokens | Monotonic token that storage validates to reject stale holders | Preventing split-brain writes after pause |
| Byzantine faults | Nodes may behave arbitrarily (lie, forge messages) | Blockchain, aerospace, adversarial settings |
| SWIM protocol | Scalable, weakly-consistent membership and failure detection | Large cluster health monitoring |

## Failure Models

### Partial Failure and Non-Determinism
**What.** In a distributed system, some nodes or network links can fail while others remain healthy, and the working parts have no immediate way to know the state of the failed parts. This non-determinism — you cannot tell if a remote node is dead, slow, or if the network lost your message — is what fundamentally separates distributed programming from single-machine programming.
**Use when.** Every design decision in a multi-node architecture must account for partial failure; it is not an edge case but the default operating condition.
**Advantages.**
- Accepting partial failure enables horizontal scaling and geographic distribution
- Commodity hardware becomes viable since individual failures are tolerated
**Tradeoffs.**
- Every interaction requires explicit handling of ambiguous outcomes (did the remote side receive it?)
- Testing all failure combinations is combinatorially explosive
**Staff signal.** The key insight is that partial failure makes outcomes non-deterministic at the application level: the same request can succeed, fail, or — worst — succeed on the remote side while appearing to fail locally, creating invisible state divergence.

### Cloud/Commodity vs Supercomputer Failure Model
**What.** Supercomputers treat the system as a single unit: if any part fails, the whole job checkpoints and restarts. Cloud systems assume components fail continuously and build software-level fault tolerance, keeping the system available during partial failures.
**Use when.** Justifying why distributed protocols are necessary rather than simply relying on hardware reliability.
**Advantages.**
- Cloud model: rolling upgrades, geographic distribution, no single-point-of-failure by design
- Supercomputer model: simpler programming model for tightly-coupled computation (HPC, simulations)
**Tradeoffs.**
- Cloud model requires far more complex software (consensus, replication, retry logic)
- Supercomputer model wastes enormous work on any single-component failure
**Staff signal.** Most real systems sit between these extremes — a rack-scale system might treat intra-rack communication as nearly reliable while treating cross-datacenter links as adversarial.

## Networks

### Unreliable Networks and the Indistinguishability Problem
**What.** In an asynchronous network, if you send a message and receive no reply, you cannot determine whether: (a) the remote node crashed, (b) the remote node is slow, (c) the request was lost, (d) the response was lost. All four cases look identical to the sender.
**Use when.** Deciding timeout values, designing idempotent operations, arguing why "just add a retry" is insufficient without idempotency.
**Advantages.**
- Acknowledging this forces designs toward idempotent APIs and explicit state machines
- Enables asynchronous, decoupled architectures
**Tradeoffs.**
- No finite timeout can perfectly distinguish a crashed node from a slow one
- Every RPC is semantically "at-most-once" without application-level deduplication
**Staff signal.** The impossibility of distinguishing slow from dead is not a bug to be fixed — it is a fundamental property of asynchronous systems. Protocols must be designed around it, not in spite of it.

### Network Partitions, Asymmetric Partitions, Gray Failures
**What.** A partition splits the network into groups that cannot communicate. Asymmetric partitions allow A→B but not B→A. Gray failures are partial degradations — a node can reach some peers but not others, or drops packets intermittently — making them harder to detect than total failures.
**Use when.** Evaluating CAP trade-offs; designing failure detectors that handle non-binary failure modes.
**Advantages.**
- Designing for partitions forces clear ownership of consistency vs availability decisions
- Gray failure awareness prevents over-reliance on simple heartbeat mechanisms
**Tradeoffs.**
- Asymmetric partitions can fool leader election (a leader thinks it is fine; followers disagree)
- Gray failures may persist for minutes without triggering alerts
**Staff signal.** Gray failures are the most operationally dangerous because they violate the binary alive/dead assumption baked into most failure detectors. A node with 5% packet loss looks alive to health checks but causes cascading timeouts.

### Timeouts and Adaptive Failure Detection
**What.** A timeout is the only mechanism to suspect failure in an asynchronous network. Too short: you falsely declare healthy nodes dead (premature declaration). Too long: the system is unavailable while waiting. Adaptive approaches (like the phi-accrual failure detector) track observed latency distributions and output a continuous suspicion score rather than a binary verdict.
**Use when.** Configuring heartbeat intervals, choosing leader-election timeouts, building health-check systems.
**Advantages.**
- Phi-accrual adapts to network conditions without manual tuning
- Continuous suspicion levels let different actions trigger at different thresholds
**Tradeoffs.**
- Adaptive detectors require a warm-up period to build a latency model
- No timeout strategy eliminates the fundamental tradeoff — only shifts the operating point
**Staff signal.** The optimal timeout depends on the cost asymmetry: if falsely declaring a node dead triggers expensive failover (e.g., re-replicating 1 TB), you want longer timeouts. If the cost of delayed detection is user-visible downtime, you want shorter ones.

### Network Congestion and Queueing
**What.** Latency variability in networks arises primarily from queueing: NIC buffers, switch queues, OS receive buffers, and TCP retransmission timers. Under load, tail latencies can spike by orders of magnitude while median latency remains stable.
**Use when.** Diagnosing latency spikes, capacity planning, setting timeout bounds.
**Advantages.**
- Understanding queueing identifies actionable bottlenecks (buffer sizing, TCP tuning)
- Explains why p99 latency diverges sharply from p50 under load
**Tradeoffs.**
- TCP's exponential backoff means a single retransmission can add seconds of delay
- Head-of-line blocking in TCP multiplexed connections amplifies congestion effects
**Staff signal.** In datacenter networks, the dominant queueing delay is often at the receiver's kernel buffer when an application thread is delayed (GC, scheduling). This is why application-level flow control and backpressure matter even on fast networks.

## Time

### Monotonic vs Time-of-Day Clocks
**What.** Time-of-day clocks report wall-clock time (synced via NTP), but can jump backward on adjustment. Monotonic clocks only ever advance and measure elapsed duration — but have no meaning across machines.
**Use when.** Measuring elapsed time locally (monotonic). Correlating events for humans, TTL enforcement (time-of-day, with awareness of its hazards).
**Advantages.**
- Monotonic clocks: safe for timeouts, performance measurement, lease duration
- Time-of-day clocks: meaningful to humans, interoperable across systems
**Tradeoffs.**
- NTP can step time backward or forward by seconds; code assuming monotonic wall-clock will break
- Clock drift between NTP syncs can be 100s of milliseconds on commodity hardware
**Staff signal.** A common production bug: using `System.currentTimeMillis()` for cache TTL, then NTP steps the clock forward by minutes and mass-expires the entire cache simultaneously.

### Clock Skew, Timestamps for Ordering, and Last-Write-Wins Data Loss
**What.** Different nodes have different clock values at the same real instant. Using timestamps to determine "which write came last" across nodes is therefore unreliable — a node with a fast clock will always "win" even if its write was causally later. Last-write-wins (LWW) with physical timestamps silently discards writes.
**Use when.** Evaluating conflict resolution strategies; understanding why Cassandra LWW can lose acknowledged writes.
**Advantages.**
- LWW is simple, requires no coordination, and always converges
**Tradeoffs.**
- Silently drops concurrent writes with no notification to clients
- Skewed clocks make the "last" determination arbitrary, not causal
**Staff signal.** LWW's danger is not the obvious case (two writes 1 ms apart) but the subtle one: two writes seconds apart on nodes with seconds of skew — the causally-later write is discarded because the originating node's clock was behind.

### Logical Clocks: Lamport Timestamps
**What.** A Lamport timestamp is a single integer counter: each node increments on local events and takes the max of (local, received) + 1 on message receipt. This produces a total order consistent with causality, but cannot determine whether two events are concurrent — if `L(a) < L(b)`, you cannot conclude `a → b`.
**Use when.** Establishing a total ordering for tie-breaking (e.g., conflict resolution) when causal ordering alone is insufficient.
**Advantages.**
- Compact (single integer), no coordination needed
- Consistent with happens-before: if a→b then L(a) < L(b)
**Tradeoffs.**
- Cannot detect concurrency: L(a) < L(b) does not imply a causally precedes b
- Insufficient for uniqueness constraints (two nodes can independently assign "next" to different operations)
**Staff signal.** Lamport timestamps give a total order, but it is one of many valid total orders — it is not uniquely determined, so two nodes cannot independently agree on the same order without communication.

### Vector Clocks and Version Vectors
**What.** A vector clock maintains one counter per node: `[N1:3, N2:5, N3:1]`. Event A happens-before B iff A's vector is component-wise ≤ B's. If neither dominates, the events are concurrent. Version vectors are the same mechanism applied at the data-item level for replica conflict detection.
**Use when.** Detecting concurrent writes in multi-leader or leaderless replication (Dynamo-style); deciding when to merge vs overwrite.
**Advantages.**
- Precisely identifies concurrent operations — enables intelligent conflict resolution
- No dependency on physical clocks
**Tradeoffs.**
- Vector size grows with number of actors/nodes; impractical at very large scale without pruning
- Clients must handle merge of concurrent values (siblings in Riak)
**Staff signal.** The practical limitation is not storage (vectors are small) but garbage collection: you need a mechanism to retire entries for departed nodes, which itself requires coordination.

### Hybrid Logical Clocks (HLC)
**What.** HLC combines a physical timestamp with a logical counter. It is always ≥ the physical clock and ≥ any received HLC value, preserving causality while staying close to real time. Used by CockroachDB for transaction ordering.
**Use when.** You need causal ordering with timestamps that are still meaningful as approximate wall-clock values.
**Advantages.**
- Causality-respecting like logical clocks; human-readable like physical clocks
- Bounded drift from real time (unlike pure Lamport counters which can diverge)
**Tradeoffs.**
- Does not provide the bounded-uncertainty guarantee of TrueTime
- Still cannot provide true external consistency without commit-wait or similar
**Staff signal.** HLC lets CockroachDB avoid the GPS/atomic clock hardware that Spanner requires, at the cost of occasionally needing to wait for clock uncertainty to pass (clock skew restart).

### TrueTime and Confidence Intervals
**What.** Google's TrueTime API returns an interval `[earliest, latest]` rather than a single timestamp, making clock uncertainty explicit. Spanner's commit-wait protocol delays commits until the uncertainty interval has passed, guaranteeing that if transaction T1 commits before T2 starts, T1's timestamp < T2's timestamp (external consistency).
**Use when.** Achieving linearizable/externally-consistent reads without consensus on every read — Spanner's globally-distributed consistent reads.
**Advantages.**
- Enables lock-free consistent reads at a past timestamp across global replicas
- Eliminates the "timestamp ordering is unsafe" problem by bounding and waiting out uncertainty
**Tradeoffs.**
- Requires GPS receivers and atomic clocks in every datacenter (significant hardware investment)
- Commit latency includes a wait proportional to clock uncertainty (~7 ms typically)
**Staff signal.** The genius of TrueTime is not eliminating clock skew — it is making the uncertainty explicit and small enough that waiting it out is cheaper than running consensus.

## Process Pauses and Fencing

### Process Pauses
**What.** Any thread or process can be suspended for an unbounded duration: GC stop-the-world pauses, VM live migration, thrashing to swap, context switches under load, or even a debugger attaching. During a pause, the node cannot know it is paused — it resumes believing no time has passed.
**Use when.** Designing any lease-based or timeout-based protocol; arguing why local state (including "I hold the lock") can become stale.
**Advantages.**
- Understanding pauses motivates fencing-based designs that are safe regardless of pause duration
**Tradeoffs.**
- Makes all time-based assertions (leases, lock TTLs) fundamentally unsafe without external validation
- GC pauses in Java/Go can be 10s–100s of milliseconds; VM migration can be seconds
**Staff signal.** The critical failure mode: a lock-holder is paused, the lease expires, another node acquires the lock and writes, the original node resumes and also writes — producing inconsistency with both nodes believing they held the lock.

### Fencing Tokens
**What.** Every time a lock/lease is granted, the lock service issues a monotonically-increasing token. The storage layer rejects any write whose token is lower than the highest token it has already seen. This makes it impossible for a stale lock-holder (paused and resumed) to corrupt data, because its old token will be rejected.
**Use when.** Any distributed lock or lease that guards mutable state.
**Advantages.**
- Correctness does not depend on timing assumptions — safe even with unbounded pauses
- Simple to implement: one integer comparison at the storage layer
**Tradeoffs.**
- Requires the storage/resource being protected to participate (must check the token)
- The lock service must guarantee strict monotonicity of tokens (itself requires consensus)
**Staff signal.** This is the standard rebuttal to the "Redlock is safe" argument: without fencing tokens validated by the downstream resource, no lock protocol based solely on timeouts can be safe against process pauses.

## Byzantine Faults and Failure Detection

### Byzantine Faults
**What.** A Byzantine-faulty node may behave arbitrarily: sending conflicting messages to different peers, lying about its state, or corrupting data. BFT protocols (PBFT, Tendermint) tolerate up to f < n/3 Byzantine nodes — at enormous cost in message complexity (O(n²) per decision).
**Use when.** Multi-party systems without mutual trust: public blockchains, aircraft flight-control systems with redundant computers from different manufacturers.
**Advantages.**
- Correctness even when some participants are actively malicious
**Tradeoffs.**
- 3f+1 nodes needed to tolerate f faults (vs 2f+1 for crash faults)
- Message overhead makes BFT impractical for high-throughput internal systems
**Staff signal.** In most datacenter systems, Byzantine tolerance is not needed because you control all nodes. The real threat is bugs and misconfiguration, which BFT cannot help with (a correlated bug is not an independent Byzantine fault).

### Failure Detection: Heartbeats, Gossip, SWIM
**What.** Heartbeat-based detection has every node periodically ping a central monitor or peers directly. Gossip-based protocols (SWIM) propagate membership changes probabilistically: a node suspecting failure asks k random peers to probe the suspect, limiting false positives and scaling O(log n) in dissemination.
**Use when.** Membership management in large clusters (Consul, Serf, Cassandra's gossip).
**Advantages.**
- SWIM: O(1) per-node message load, infection-style dissemination, tunable false-positive rate
- Decentralized: no single failure detector that is itself a SPOF
**Tradeoffs.**
- Gossip has propagation delay — membership changes are eventually consistent, not instantaneous
- Indirect probing adds detection latency compared to direct heartbeats
**Staff signal.** SWIM's key innovation is separating failure detection (protocol period probes) from dissemination (piggybacking membership updates on protocol messages), achieving scalability without sacrificing detection speed.

## Common interview traps

- Claiming you can reliably distinguish a crashed node from a slow one in an async network — you cannot; you can only suspect after a timeout.
- Confusing monotonic clocks with time-of-day clocks; using `time.Now()` for both duration measurement and cross-node ordering.
- Believing NTP keeps clocks perfectly synchronized — typical datacenter skew is 1–10 ms, and steps can be much larger.
- Assuming a lease holder is safe for the lease duration — a GC pause can stall execution past lease expiry without the holder knowing.
- Stating "vector clocks give a total order" — they give a partial order; concurrent events are incomparable.
- Claiming Lamport timestamps can detect concurrency — they cannot; L(a) < L(b) does not imply a→b.
- Treating Byzantine fault tolerance as necessary for internal services — the cost is rarely justified when you control all nodes.
- Forgetting that fencing tokens require cooperation from the storage layer, not just the lock service.

## Drill questions

1. A node holding a leader lease is paused by a 15-second GC pause. Its lease was 10 seconds. Walk through exactly what can go wrong and how fencing tokens prevent data corruption.
2. You observe a Cassandra cluster losing acknowledged writes under normal operation with LWW conflict resolution. What is the most likely root cause, and how would you confirm it?
3. Why can't Lamport timestamps be used to implement a distributed uniqueness constraint (e.g., unique usernames) without additional coordination?
4. Explain why vector clocks grow in size and describe two practical strategies for bounding their size. What correctness properties do you lose with each strategy?
5. A service uses a 5-second heartbeat interval and a 15-second timeout. Traffic spikes cause p99 network latency to reach 8 seconds. What happens, and how would an adaptive failure detector behave differently?
6. Why does Spanner need GPS and atomic clocks while CockroachDB does not? What does CockroachDB give up in exchange?
7. Describe a scenario where an asymmetric network partition causes split-brain even with a majority-based leader election protocol.
8. What is the precise difference between a safety property and a liveness property? Give an example of each in the context of consensus.
9. Why is the SWIM protocol preferred over all-to-all heartbeats in a 5,000-node cluster? What is the detection latency trade-off?
10. A system uses NTP-synchronized timestamps to order events across three datacenters. Under what conditions does this produce incorrect orderings, and what is the maximum magnitude of the error?
