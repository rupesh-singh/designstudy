# 1. Foundations, Non-Functional Requirements & Estimation

Every system-design discussion begins with clarifying what "good" means for this particular system. This section covers the vocabulary for expressing non-functional requirements (reliability, availability, scalability, maintainability), the mathematical tools for reasoning about capacity (Little's Law, Amdahl's Law, queueing intuition), and the estimation techniques that let you validate or reject an architecture on the back of an envelope before writing any code.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Reliability | System works correctly despite faults | Defining tolerance for hardware/software/human errors |
| Availability | Fraction of time the system is operational | Setting SLOs, reasoning about redundancy |
| Scalability | Ability to handle growing load | Load is changing and you need to articulate how |
| Maintainability | Ease of operating, understanding, and evolving | Justifying design choices beyond pure performance |
| Vertical vs Horizontal scaling | Single-machine growth vs multi-machine distribution | Choosing architecture shape early in design |
| Latency vs Response time | Time-in-system vs time-observed-by-caller | Precisely specifying SLOs |
| Percentiles | Distribution-aware latency characterization | Avoiding the trap of averages |
| Tail latency amplification | Fan-out magnifies high percentiles | Designing systems with many parallel backend calls |
| Head-of-line blocking | One slow item stalls everything behind it | Diagnosing queue-based latency spikes |
| Throughput & Little's Law | Relating concurrency, throughput, and latency | Capacity planning and thread-pool sizing |
| Amdahl's Law & USL | Limits of parallelism | Arguing diminishing returns of adding machines |
| Back-of-envelope estimation | Order-of-magnitude feasibility check | First five minutes of any design interview |
| SLI / SLO / SLA | Measuring, targeting, and contracting reliability | Defining what "good enough" means operationally |
| Load testing & chaos engineering | Validating assumptions under stress | Pre-launch or post-scaling readiness |
| Graceful degradation | Controlled quality reduction under overload | Designing for partial failure states |

## Reliability and Fault Tolerance

### Reliability
**What.** A system is reliable when it continues to perform its intended function correctly — delivering correct results, at acceptable performance, even when things go wrong. A *fault* is a component deviating from spec; a *failure* is the system as a whole ceasing to provide service. Fault tolerance means the system handles faults without escalating them to failures.
**Use when.** You must articulate what can go wrong (hardware: disk dies, memory corrupts; software: cascading bugs triggered by unusual input; human: misconfiguration during deploy) and how the system survives it.
**Advantages.**
- Users experience uninterrupted service despite individual component faults
- Fault isolation prevents blast radius from growing
**Tradeoffs.**
- Every fault-tolerance mechanism adds complexity and cost (redundant hardware, retry logic, state reconciliation)
- Testing fault-tolerance paths is hard; they rot if never exercised (hence chaos engineering)
**Staff signal.** Distinguish between *preventing* faults (impossible in general) and *tolerating* faults (practical). Note that software faults are correlated (one bug hits all replicas simultaneously), unlike random hardware failures, which makes software faults harder to tolerate through simple redundancy.

### Availability
**What.** The proportion of time a system is operational and serving correct responses. Measured in "nines": 99.9% ≈ 8.7 hours downtime/year; 99.99% ≈ 52 minutes/year. When dependencies are in series, their availabilities multiply (two 99.9% services in series → 99.8%). In parallel (active redundancy), unavailabilities multiply (two 99% nodes in parallel → 99.99%).
**Use when.** Setting SLOs, deciding replication factor, or justifying redundant paths.
**Advantages.**
- Precise language for contractual guarantees
- Composition rules let you compute end-to-end availability from component figures
**Tradeoffs.**
- Higher nines cost exponentially more in engineering, infrastructure, and operational discipline
- Availability says nothing about correctness — a system can be "up" but returning stale data
**Staff signal.** In practice the serial composition formula is pessimistic (assumes independent failures); correlated failures (shared network, same deploy) can make it worse. Also note that adding a dependency *always* reduces serial availability unless it is optional.

## Scalability

### Scalability
**What.** The ability of a system to cope with increased load without degrading key metrics (latency, throughput, error rate). Describing load requires *load parameters* — the specific numbers that characterize demand: requests/sec, concurrent users, read/write ratio, data volume growth, fan-out factor.
**Use when.** The system must handle 10× growth, or current load is approaching capacity.
**Advantages.**
- A well-described load model lets you reason quantitatively about bottlenecks
- Separates "can we scale?" from "should we scale?" (cost consideration)
**Tradeoffs.**
- Scaling architectures add distributed-systems complexity (partitioning, coordination)
- No single architecture scales all dimensions equally; optimize for the dominant load parameter
**Staff signal.** Always define the *specific* dimension of load you're scaling (QPS? data volume? fan-out?) before proposing a solution. "It doesn't scale" is meaningless without stating which parameter saturates first.

### Vertical vs Horizontal Scaling
**What.** Vertical (scale-up): bigger machine — more CPU, RAM, disk. Horizontal (scale-out): more machines, sharing the workload. Three architecture classes: shared-memory (one OS, many CPUs/RAM — limited by bus and cost), shared-disk (multiple machines, one storage layer — e.g., Oracle RAC), shared-nothing (each node owns its slice of data — standard for web-scale systems like Cassandra, CockroachDB).
**Use when.** Choosing the fundamental shape of your system's growth path.
**Advantages.**
- Vertical: simpler operations, no distribution complexity, good up to a surprisingly high point (modern machines have 100+ cores, terabytes of RAM)
- Horizontal/shared-nothing: near-linear scaling ceiling, commodity hardware, fault isolation per node
**Tradeoffs.**
- Vertical hits a cost/physical ceiling and is a single point of failure
- Horizontal introduces coordination overhead, partial-failure modes, and data distribution challenges
**Staff signal.** Shared-nothing is dominant but not always correct. If your dataset fits in one large machine's memory, vertical scaling avoids years of distributed-systems pain. The decision is economic and operational, not just technical.

### Maintainability
**What.** Three sub-properties: *operability* (easy to keep running — monitoring, deploy, config), *simplicity* (new engineers can understand it — few accidental complexities, good abstractions), *evolvability* (easy to change for new requirements — loose coupling, clean interfaces).
**Use when.** Justifying design choices that don't directly improve performance but reduce long-term cost.
**Advantages.**
- Majority of software cost is ongoing maintenance, not initial build
- Reduces human-fault rate (the dominant fault source in production)
**Tradeoffs.**
- Investing in maintainability upfront delays shipping; requires judgment on how much is enough
- Over-abstraction for hypothetical future needs hurts simplicity
**Staff signal.** In interviews, explicitly naming maintainability as a design goal and showing how your architecture supports operational teams (runbooks, observability hooks, safe deploys) demonstrates staff-level thinking.

## Latency, Percentiles & Queueing

### Latency vs Response Time vs Service Time
**What.** *Service time*: how long the actual work takes. *Latency*: time spent waiting before work begins (queue time, network transit). *Response time*: what the client observes — service time + latency + network return. Many people conflate latency and response time; in interviews, precision matters.
**Use when.** Specifying SLOs or diagnosing where time is spent.
**Advantages.**
- Decomposing response time lets you identify whether to fix the queue, the network, or the handler
**Tradeoffs.**
- Measuring true service time requires instrumentation at the handler entry, not the client
**Staff signal.** When a peer says "latency is 200ms," ask: measured where? Client-side response time includes everything; server-side service time hides queueing delays.

### Percentiles and Tail Latency
**What.** p50 (median) is the typical experience; p95/p99/p99.9 capture the worst-case experiences that affect your most active (and often most valuable) users. Averages are misleading because a few extreme outliers shift the mean without revealing the shape of the distribution.
**Use when.** Defining SLOs (use percentiles, not averages), diagnosing user-reported slowness.
**Advantages.**
- Percentiles give actionable guarantees: "99% of requests complete within X ms"
- They reveal bimodal distributions that averages hide
**Tradeoffs.**
- Collecting and aggregating percentiles is harder than averages (cannot simply average percentiles across nodes — need merging algorithms like t-digest or HDR histogram)
- Very high percentiles (p99.99) are expensive to optimize and may not be cost-effective
**Staff signal.** Know that you cannot average p99 across multiple machines; you must merge the full histograms or use approximate streaming structures.

### Tail Latency Amplification
**What.** When a single user request fans out to N backend services in parallel, the overall response time is the slowest of the N calls. Even if each service has only 1% chance of being slow, with 100 parallel calls the user almost certainly hits at least one slow call. This is tail latency amplification.
**Use when.** Designing aggregation layers, search fan-out, or any scatter-gather pattern.
**Advantages.**
- Understanding this drives mitigation: hedged requests (send duplicate request to a second replica after a delay), tied requests (pre-coordinate which replica is backup), or reducing fan-out.
**Tradeoffs.**
- Hedged/tied requests increase backend load (extra requests), requiring headroom
- Reducing fan-out may hurt completeness (e.g., skipping some shards in search)
**Staff signal.** Google's Jeff Dean paper showed tied requests are more efficient than hedged because they cancel redundant work. Mention this for instant credibility.

### Head-of-Line Blocking
**What.** When a queue (thread pool, network connection, TCP stream) processes items sequentially, one slow item delays all items behind it regardless of their individual cost. Occurs in HTTP/1.1 pipelining, single-threaded event loops when a handler blocks, and OS socket accept queues.
**Use when.** Diagnosing p99 spikes that don't correlate with actual request complexity.
**Advantages.**
- Identifying HOL blocking points you toward solutions: multiple connections (HTTP/2 multiplexing), separate queues by priority, timeouts on individual items
**Tradeoffs.**
- Multiple connections/queues increase resource usage and complexity
**Staff signal.** HTTP/2 solves HOL at the HTTP layer via stream multiplexing, but TCP itself still has HOL blocking (one lost packet stalls all streams). QUIC (HTTP/3) solves this at the transport layer by using independent UDP streams.

## Throughput, Queueing Theory & Scaling Laws

### Throughput and Little's Law
**What.** Little's Law: L = λW (average items in system = arrival rate × average time each item spends in system). Equivalently: concurrency = throughput × latency. If your service handles requests in 100ms average and you need 1000 QPS, you need 100 concurrent slots (threads, connections, etc.).
**Use when.** Sizing thread pools, connection pools, determining required parallelism.
**Advantages.**
- Simple, universally applicable, requires no distributional assumptions
- Directly connects capacity planning to measurable quantities
**Tradeoffs.**
- Assumes a stable system (arrival rate ≤ service rate over time); doesn't apply during overload
**Staff signal.** Use Little's Law in estimation segments of interviews to show rigorous capacity reasoning rather than guessing thread counts.

### Utilization vs Latency (Queueing Intuition)
**What.** From basic queueing theory (M/M/1): as utilization ρ approaches 1, average queue wait time → infinity (proportional to 1/(1−ρ)). At 50% utilization, average wait equals service time. At 90% utilization, average wait is 9× service time. This is why you never plan to run services at >70-80% utilization.
**Use when.** Justifying headroom in capacity planning; explaining why autoscaling needs to trigger well before saturation.
**Advantages.**
- Makes the abstract concept of "headroom" concrete and quantitative
**Tradeoffs.**
- Real systems don't follow M/M/1 exactly (correlated arrivals, variable service times), but the explosive growth near saturation is universal
**Staff signal.** Cite this to explain why a service with "enough average capacity" still has latency spikes — variance + high utilization causes queue buildup even when mean rate is below capacity.

### Amdahl's Law and Universal Scalability Law
**What.** Amdahl's Law: speedup from parallelism is limited by the serial fraction. If 5% of work is serial, maximum speedup is 20× regardless of cores/machines. The Universal Scalability Law (Gunther) adds a coherency/crosstalk penalty — as you add nodes, coordination overhead (cache invalidation, lock contention, consensus rounds) can cause throughput to actually *decrease* past an optimal point.
**Use when.** Arguing that simply adding machines won't solve a bottleneck; identifying serialization points or coordination costs.
**Advantages.**
- Provides quantitative framework for diminishing returns
- USL explains why some systems get *slower* after a certain cluster size
**Tradeoffs.**
- Finding the serial fraction or coherency coefficient requires measurement, not just theory
**Staff signal.** When a candidate says "just add more nodes," counter with USL: what's the coordination cost? Distributed locks, consensus rounds, cross-partition queries — these are the coherency terms that cap scalability.

## Estimation & Numbers

### Back-of-the-Envelope Estimation

**What.** Rapid order-of-magnitude calculations using memorized hardware/network numbers to validate whether an architecture is feasible before detailed design.
**Use when.** First 5 minutes of any design discussion; validating that your proposal is physically possible.

#### Numbers Every Engineer Should Know (Approximate, 2020s Hardware)

| Operation | Order of Magnitude |
|-----------|--------------------|
| L1 cache reference | ~1 ns |
| L2 cache reference | ~4 ns |
| Main memory (DRAM) reference | ~100 ns |
| SSD random read (4KB) | ~100 μs |
| HDD random read | ~10 ms |
| Same-datacenter network round trip | ~0.5 ms |
| Cross-region network round trip (e.g., US-East ↔ EU-West) | ~50–150 ms |
| Read 1 MB sequentially from memory | ~10 μs |
| Read 1 MB sequentially from SSD | ~1 ms |
| Read 1 MB sequentially from HDD | ~20 ms |
| Send 1 MB over 1 Gbps network | ~10 ms |
| Disk seek (HDD) | ~10 ms |
| TCP handshake (same DC) | ~0.5 ms |
| Compress 1KB with Snappy | ~3 μs |

**Staff signal.** Use these to anchor your estimates, but always label them as approximate. Interviewers care about the method and order-of-magnitude reasoning, not exact figures.

### Capacity Planning and Headroom
**What.** Determining how much infrastructure is needed to handle projected load with sufficient margin for traffic spikes, component failures, and growth. Rule of thumb: provision for peak load × 1.5–2× to absorb spikes and allow one-node failures without cascading.
**Use when.** Sizing clusters, budgeting storage growth, planning autoscaling thresholds.
**Advantages.**
- Prevents cascading failures during traffic surges
- Gives time to react before saturation
**Tradeoffs.**
- Over-provisioning wastes money; under-provisioning causes outages
- Headroom must be re-evaluated as traffic patterns change
**Staff signal.** Connect headroom to the queueing theory insight: at 80% utilization, latency is already 4× service time. Headroom isn't "wasted capacity" — it's latency insurance.

## Operational Concepts

### SLI / SLO / SLA and Error Budgets
**What.** *SLI* (Service Level Indicator): a measured metric (e.g., proportion of requests faster than 300ms). *SLO* (Service Level Objective): the target value for an SLI (e.g., 99.9% of requests < 300ms). *SLA* (Service Level Agreement): the contractual commitment with consequences (refunds, credits) if SLOs are breached. An *error budget* is the tolerable amount of unreliability (1 − SLO); teams can "spend" it on risky deploys or feature velocity.
**Use when.** Defining reliability requirements, balancing reliability investment against feature velocity.
**Advantages.**
- Makes reliability discussions quantitative and negotiable
- Error budgets align incentives: when budget is exhausted, focus shifts to stability
**Tradeoffs.**
- Setting SLOs too tight wastes engineering effort; too loose and users suffer
- SLAs create legal obligations; set them less aggressively than internal SLOs
**Staff signal.** SLAs should be strictly weaker than SLOs (buffer zone). If your SLO is 99.95%, your SLA might be 99.9%. This gives you room to detect and fix before contractual breach.

### Load Testing, Shadow Traffic & Chaos Engineering
**What.** Load testing: synthetic traffic at expected or beyond-expected levels to find breaking points. Shadow/mirrored traffic: copying real production traffic to a test environment for realistic testing without user impact. Chaos engineering: deliberately injecting failures (kill nodes, add latency, corrupt packets) to verify the system tolerates faults as designed.
**Use when.** Before launches, after scaling changes, or continuously (chaos) to prevent confidence decay.
**Advantages.**
- Finds bottlenecks and failure modes before users do
- Shadow traffic reveals issues synthetic tests miss (real-world distributions)
**Tradeoffs.**
- Load tests require representative traffic patterns to be useful (garbage in, garbage out)
- Chaos engineering requires strong observability and runbooks — don't inject faults you can't detect
**Staff signal.** Netflix's Chaos Monkey kills random instances; their Chaos Kong simulates entire region failures. The discipline is running these *in production* regularly, not just in staging.

### Graceful Degradation
**What.** When the system is under excessive load or partial failure, intentionally reducing service quality (serving cached/stale results, disabling non-critical features, shedding low-priority traffic) rather than failing completely.
**Use when.** Any system with varying request priority or optional features.
**Advantages.**
- Core user experience survives even during overload
- Buys time for recovery without total outage
**Tradeoffs.**
- Requires pre-planned degradation modes (you can't improvise under stress)
- Users of degraded features still experience pain; communication matters
**Staff signal.** Design degradation levels upfront (level 1: disable recommendations; level 2: serve stale data; level 3: static error page). Circuit breakers (Hystrix-pattern) automate transitions between levels.

## Common interview traps

- Confusing availability with reliability — a system can be available (responding) but unreliable (returning wrong answers).
- Quoting an average latency as an SLO — percentiles are the correct tool.
- Saying "just add more servers" without identifying the serial/coordination bottleneck (Amdahl's/USL).
- Multiplying availabilities for parallel (redundant) systems — you should multiply *un*availabilities.
- Using SLA and SLO interchangeably — SLA is the contract with penalties; SLO is the internal target.
- Estimating storage without accounting for replication factor (3× for typical distributed systems).
- Ignoring queueing effects at high utilization when estimating required QPS capacity.
- Confusing latency (time waiting) with response time (total time from request to response including processing).

## Drill questions

1. Your system has three serial dependencies, each at 99.9% availability. What's the composite availability? What if you add a fourth? How would you improve it?
2. A service runs at 70% CPU utilization with p50 latency of 20ms. Predict what happens to p99 if traffic doubles. Why?
3. You fan out a user request to 50 microservices in parallel. Each has p99 of 50ms. What's the likely p99 the user experiences? How would you mitigate this?
4. Your system needs to handle 100K QPS with 10ms average processing time. Using Little's Law, how many concurrent handler slots do you need?
5. A component has 5% serial work. What's the maximum speedup from adding cores, per Amdahl's Law? What does USL add to this analysis?
6. Estimate the storage needed for a system storing 1 billion 1KB messages per day for 7 days with 3× replication.
7. When would you choose vertical scaling over horizontal? Give a concrete example.
8. Your error budget is 0.1% (99.9% SLO). You've used 80% of it in the first week of the month. What actions do you take?
9. How would you design a graceful degradation strategy for an e-commerce checkout flow?
10. Why can't you simply average p99 values across 10 servers to get the system-wide p99?
