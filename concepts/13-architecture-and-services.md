# 13. Architecture Styles & Service Design

How you decompose a system into deployable units determines your team's velocity, operational burden, and ability to evolve independently. This section covers the structural patterns, migration strategies, and economic reasoning that shape service boundaries.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Monolith / Modular monolith | Single deployment unit with internal module boundaries | Early product, small team, unclear domain boundaries |
| Microservices | Independently deployable services per bounded context | Teams need independent release cadence at scale |
| Service granularity | Right-sizing service boundaries | Splitting or merging services |
| Conway's Law | Org structure shapes system architecture | Designing team/service alignment |
| DDD essentials | Bounded contexts & aggregates as design tools | Defining service boundaries and consistency scopes |
| Database-per-service | Data isolation across services | Enabling independent schema evolution |
| API composition vs CQRS | Cross-service query strategies | Reading data that spans multiple services |
| CQRS | Separate read and write models | Read/write workloads with divergent scaling needs |
| Event-driven architecture | Async communication via events | Decoupling producers from consumers |
| Saga pattern | Distributed transaction coordination | Multi-service business transactions |
| Strangler fig | Incremental migration from legacy | Replacing systems without big-bang rewrites |
| Anti-corruption layer | Translation boundary to legacy/external systems | Integrating with a model you don't control |
| BFF | Tailored API per client type | Mobile vs web with divergent data needs |
| Sidecar / Service mesh | Cross-cutting concerns as infrastructure | Uniform mTLS, observability, retries across polyglot services |
| Serverless / FaaS | Event-triggered stateless compute | Bursty, short-lived, infrequent workloads |
| Containers & orchestration | Packaged deployment with scheduling | Consistent environments with autoscaling |
| Autoscaling | Dynamic capacity matching demand | Variable traffic patterns |
| Stateful vs stateless | Where state lives determines scalability | Designing for horizontal scale |
| Batch / worker tiers | Async job processing | Long-running or deferrable computation |
| Layered vs hexagonal | Internal code organization | Keeping domain logic testable and portable |
| Build vs buy | Make/use managed service decision | Every infrastructure component choice |
| Migration patterns | Safe cutover techniques | Moving traffic between implementations |
| Data migration: expand-contract | Schema evolution without downtime | Changing data shapes in production |
| Versioning & compatibility | Stable contracts across boundaries | Evolving APIs without breaking consumers |
| Technical debt & evolvability | Architecture that remains changeable | Long-lived systems under continuous delivery |
| Cost as constraint | Unit economics shaping design | High-scale systems where infra spend matters |

## Structural Patterns

### Monolith (and Modular Monolith)
**What.** A single deployable unit containing all application code. A modular monolith adds strict internal module boundaries (explicit APIs between modules, no cross-module database queries) while retaining one deployment artifact.
**Use when.** Team is fewer than ~30 engineers; domain boundaries are not yet well understood; you need fast iteration without distributed-systems overhead. Shopify runs a large modular monolith.
**Advantages.**
- Simple local development, debugging, and testing (one process, in-memory calls)
- Transactions are local; no distributed consistency problems
- Refactoring across module boundaries is a code change, not a contract negotiation
**Tradeoffs.**
- Deployment coupling: one broken module blocks the entire release
- Scaling is all-or-nothing unless you shard by function at the infrastructure layer
- Over time, module boundaries erode without CI enforcement
**Staff signal.** The modular monolith is often superior to premature microservices because it preserves the option to extract services later when domain boundaries have proven stable — splitting a well-modularised monolith is cheap; merging poorly-cut microservices is expensive.

### Microservices
**What.** Independently deployable services, each owning its data and exposing a network API. Independence means one team can release without coordinating with others.
**Use when.** Multiple teams need autonomous release cycles; different components have fundamentally different scaling/technology needs; domain boundaries are well understood.
**Advantages.**
- Independent deployment and scaling per service
- Technology heterogeneity where it genuinely helps (e.g., ML pipeline in Python, gateway in Go)
- Fault isolation: one service's OOM does not crash others
**Tradeoffs.**
- Network calls add latency (~1 ms per hop in-datacenter, more with serialization)
- Operational overhead: each service needs CI/CD, observability, on-call ownership
- Distributed debugging is far harder (requires tracing infrastructure)
- Data consistency requires sagas, eventual consistency, or coordination
**Staff signal.** The real cost of microservices is organisational, not technical: you need platform teams, paved-road tooling, and observability infrastructure before the independence benefit pays off. Without those, you get a distributed monolith — all the latency, none of the autonomy.

### Service Granularity & Distributed Monolith Anti-Pattern
**What.** Choosing service boundaries that are too fine or too coarse. A distributed monolith emerges when services cannot be deployed independently — they share databases, require lockstep releases, or have synchronous call chains that make every request a distributed transaction.
**Use when.** Re-evaluating existing decomposition or planning a new one.
**Advantages.**
- Right-sized services align deployment independence with domain ownership
**Tradeoffs.**
- Too fine: explosion of inter-service calls, chatty networks, debugging nightmares
- Too coarse: back to monolith problems with extra network overhead
**Staff signal.** A litmus test: if changing one service routinely requires a simultaneous change in another, the boundary is in the wrong place. Merge them or redesign the contract.

### Conway's Law and Inverse Conway Manoeuvre
**What.** Conway's Law observes that system architecture mirrors communication structures of the organisation. The inverse manoeuvre deliberately shapes team topology to produce a desired architecture.
**Use when.** Planning org structure alongside a re-architecture; noticing that service boundaries don't match team ownership.
**Advantages.**
- Aligning teams to architecture reduces cross-team coordination cost
- Team Topologies (stream-aligned, platform, enabling, complicated-subsystem) give a vocabulary for this
**Tradeoffs.**
- Org changes are slow and politically expensive
- Blindly mapping teams to services can create too many services
**Staff signal.** Architecture decisions made without considering who will own and operate the resulting services routinely fail. If no single team can own a service end-to-end (build, deploy, operate), the service boundary is likely wrong.

## Domain-Driven Design Essentials

### Bounded Context, Aggregate, Ubiquitous Language
**What.** A bounded context is a linguistic and model boundary: inside it, terms have precise shared meaning (ubiquitous language). An aggregate is the consistency boundary — a cluster of entities that are always modified together within a single transaction.
**Use when.** Deciding where to draw service boundaries and transaction scopes.
**Advantages.**
- Aggregates map cleanly to transaction boundaries, avoiding distributed transactions
- Bounded contexts prevent model pollution (e.g., "Order" means different things in shipping vs billing)
**Tradeoffs.**
- Identifying good aggregates requires deep domain understanding; premature modelling is expensive to fix
- Cross-aggregate references require eventual consistency or lookup by ID
**Staff signal.** An aggregate should be as small as possible while maintaining invariants. If your aggregate is large, you pay with lock contention; if too small, you push invariant enforcement to sagas, which are harder to reason about.

## Data Ownership Patterns

### Database-per-Service
**What.** Each service owns and exclusively accesses its persistent store. Other services read that data via the owning service's API or by consuming its events.
**Use when.** You need independent schema evolution and deployment; different services need different storage engines.
**Advantages.**
- No coupling through shared schema; services evolve freely
- Storage engine choice optimised per workload (OLTP, search, graph)
**Tradeoffs.**
- Cross-service queries require API composition or materialised views
- Data duplication and eventual consistency become normal
**Staff signal.** A "shared database" doesn't just couple schemas — it couples deployment, scaling, and failure domains. However, for small teams with few services, a shared database with schema-per-service (logical isolation) can be a pragmatic intermediate step.

### API Composition vs CQRS for Cross-Service Queries
**What.** API composition aggregates responses from multiple services at query time. CQRS pre-builds a denormalised read model from events so queries hit a single optimised store.
**Use when.** A user-facing query needs data owned by multiple services.
**Advantages.**
- Composition: simple, no extra infrastructure; works for low-volume queries
- CQRS: handles high-read-volume with complex filters; decouples read scaling from write scaling
**Tradeoffs.**
- Composition: latency is the max of downstream calls; failure of one service fails the query
- CQRS: read model is eventually consistent; requires event infrastructure and projection code
**Staff signal.** Start with composition; move to CQRS only when read latency or volume demands it. Many teams adopt CQRS prematurely and underestimate the operational cost of maintaining projections and replaying events on schema change.

### CQRS
**What.** Commands (writes) go to one model; queries (reads) go to a separate model optimised for the access pattern. The read model is updated asynchronously from write-side events.
**Use when.** Read and write workloads differ in shape, volume, or scaling needs; complex queries against event-sourced data.
**Advantages.**
- Read model can be denormalised for single-query retrieval (no joins)
- Write and read sides scale independently
**Tradeoffs.**
- Eventual consistency between command acceptance and read-model update (seconds typically)
- More moving parts: event bus, projection workers, rebuild tooling
**Staff signal.** You must design for the case where a user writes and immediately reads — they might see stale data. Solutions include read-your-own-writes routing, version tokens, or synchronous projection for critical paths.

## Communication Patterns

### Event-Driven Architecture; Choreography vs Orchestration
**What.** Services communicate through events (facts about what happened). In choreography, each service reacts independently to events; in orchestration, a central coordinator directs the flow.
**Use when.** You want temporal decoupling and independent evolution of producers and consumers.
**Advantages.**
- Choreography: no single point of failure; services are truly independent
- Orchestration: business process is visible in one place; easier to reason about and debug
**Tradeoffs.**
- Choreography: the overall flow is invisible without tracing; debugging requires correlating events across logs
- Orchestration: the orchestrator becomes a coupling point and potential bottleneck
**Staff signal.** Choreography's observability cost is routinely underestimated. Without investment in distributed tracing and process-level dashboards, teams lose visibility into end-to-end flows and discover failures only through downstream symptoms.

### Saga Pattern (Architecture Context)
**What.** A sequence of local transactions across services, each with a compensating action for rollback. Either choreographed (event-triggered steps) or orchestrated (central saga coordinator).
**Use when.** A business operation spans multiple services that each own their data.
**Advantages.**
- Achieves cross-service consistency without distributed locks
**Tradeoffs.**
- Compensation logic is domain-specific and must be idempotent
- Partial-execution states are visible to users (semantic isolation is weak)
**Staff signal.** Sagas do not provide isolation — concurrent operations can see intermediate states. If the business cannot tolerate this, consider restructuring aggregate boundaries so the transaction stays local.

## Migration & Integration Patterns

### Strangler Fig Pattern
**What.** Route traffic incrementally from a legacy system to a new implementation, feature by feature, until the old system can be decommissioned.
**Use when.** Replacing a monolith or legacy system without a risky big-bang cutover.
**Advantages.**
- Risk is incremental; rollback scope is small
- Value delivered continuously during migration
**Tradeoffs.**
- Requires a routing layer (often an API gateway or reverse proxy)
- Both systems run in parallel, increasing operational cost during migration
**Staff signal.** The hardest part is shared mutable state. If old and new both write to the same database, you haven't actually decoupled them. Plan the data migration before the traffic migration.

### Anti-Corruption Layer
**What.** A translation boundary that prevents a foreign model (legacy system, third-party API) from leaking into your domain model.
**Use when.** Integrating with systems whose data model you cannot or should not adopt.
**Advantages.**
- Keeps your domain clean; changes in the external system are absorbed by the ACL
**Tradeoffs.**
- Extra mapping code and potential latency
**Staff signal.** An ACL is not optional when integrating with legacy — without it, the legacy model infects your new services and you cannot evolve them independently.

### Backend for Frontend (BFF)
**What.** A dedicated API layer per client type (mobile, web, third-party) that aggregates, transforms, and tailors responses.
**Use when.** Different clients need significantly different data shapes or aggregation levels.
**Advantages.**
- Clients get optimised payloads; reduces over-fetching and round trips
- Mobile BFF can batch calls that a web BFF doesn't need
**Tradeoffs.**
- More services to maintain; risk of duplicating business logic in BFFs
**Staff signal.** A BFF should be thin — aggregation and formatting only. If domain logic creeps in, you've moved your microservice boundary to the wrong place.

### Sidecar Pattern and Service Mesh
**What.** A sidecar proxy (e.g., Envoy) runs alongside each service instance handling cross-cutting concerns: mTLS, retries, circuit breaking, load balancing, telemetry. A mesh (e.g., Istio) is the control plane managing all sidecars.
**Use when.** You have many polyglot services and want uniform security/observability without library changes.
**Advantages.**
- Consistent mTLS, tracing, and traffic policies without application code changes
- Enables canary routing and traffic shifting at the infrastructure layer
**Tradeoffs.**
- Each hop now traverses two proxies (source sidecar → destination sidecar): ~1-3 ms added latency per hop
- Significant operational complexity: debugging now includes the mesh layer
- Memory overhead: each sidecar consumes ~50-100 MB RAM
**Staff signal.** A service mesh is powerful but should be adopted when you have operational maturity to manage it. Teams that adopt Istio before they can run Kubernetes well tend to compound their debugging difficulty.

## Compute Models

### Serverless / FaaS
**What.** Event-triggered, stateless compute billed per invocation (e.g., AWS Lambda, Cloud Functions). The platform manages scaling and infrastructure.
**Use when.** Bursty or infrequent workloads; event processing (S3 triggers, queue consumers); prototyping.
**Advantages.**
- Zero cost at zero traffic; fine-grained cost visibility
- Scales to thousands of concurrent executions automatically
**Tradeoffs.**
- Cold starts: 100 ms – 10 s depending on runtime and VPC config
- Execution limits (15 min on Lambda); no local persistent state
- Vendor lock-in through proprietary event integrations
**Staff signal.** Serverless cost model inverts at high steady-state throughput — a container running 24/7 is often cheaper than millions of Lambda invocations. Model both cost curves before committing.

### Containers and Orchestration
**What.** Containers package application and dependencies for consistent deployment. Orchestrators (Kubernetes, ECS) handle scheduling, bin-packing, health checks, and autoscaling.
**Use when.** System design discussions that involve deployment, scaling, or resource efficiency.
**Advantages.**
- Reproducible builds; density via bin-packing; declarative desired state
- Rolling updates, self-healing, service discovery built in
**Tradeoffs.**
- Kubernetes has a steep learning curve and operational overhead
- Networking, storage, and observability all require additional configuration
**Staff signal.** In interviews, you rarely need to detail Kubernetes internals — but you should know that scheduling, bin-packing, and HPA-based autoscaling exist and how they interact with your scaling story.

### Autoscaling
**What.** Dynamically adjusting compute capacity in response to load signals. Reactive scaling triggers on current metrics; predictive scaling uses historical patterns to pre-provision.
**Use when.** Traffic is variable; over-provisioning is too expensive; under-provisioning risks SLO violation.
**Advantages.**
- Matches cost to demand; handles spikes without permanent over-provisioning
**Tradeoffs.**
- Scale-up lag (VM: minutes; container: seconds) means traffic can arrive before capacity
- Scaling on the wrong signal (CPU when the bottleneck is IO) leads to thrashing or under-scaling
**Staff signal.** Choose the metric closest to user-perceived saturation. For a queue-processing service, scale on queue depth, not CPU. For an API, scale on request latency or concurrent connections. CPU is a proxy that often lags the real constraint.

### Stateful vs Stateless Services
**What.** Stateless services hold no per-request state between calls — any instance can handle any request. State lives externally (databases, caches, object stores).
**Use when.** Designing for horizontal scalability.
**Advantages.**
- Trivial horizontal scaling: add instances behind a load balancer
- Any instance can serve any request; simpler failover
**Tradeoffs.**
- External state stores become the bottleneck and single point of failure
- Some workloads (WebSocket connections, in-memory caches) inherently carry state
**Staff signal.** "Stateless" doesn't mean no state — it means state is externalized. The design challenge moves to how that external store scales, replicates, and handles partitions.

### Batch / Worker Tiers and Job Queues
**What.** Asynchronous processing where requests are enqueued and workers pull jobs at their own pace. Decouples request acceptance from processing.
**Use when.** Work is long-running, deferrable, or benefits from batching (image processing, report generation, ETL).
**Advantages.**
- Absorbs traffic spikes without dropping requests
- Workers scale independently from the request-serving tier
**Tradeoffs.**
- Adds latency (job waits in queue); requires dead-letter handling for failures
- At-least-once delivery means workers must be idempotent
**Staff signal.** The queue is the backpressure mechanism — monitor queue depth as a leading indicator of capacity shortfall, and set autoscaling on it.

## Internal Architecture

### Layered vs Hexagonal Architecture
**What.** Layered architecture arranges code in horizontal tiers (presentation → business → data). Hexagonal (ports & adapters) centres on the domain, with infrastructure plugged in via interfaces.
**Use when.** Structuring internal service code; ensuring domain logic is testable without infrastructure.
**Advantages.**
- Hexagonal: domain is framework-agnostic; easy to swap databases, message brokers in tests
**Tradeoffs.**
- Hexagonal requires more interfaces/abstractions; overhead for simple CRUD services
**Staff signal.** Hexagonal architecture shines when business logic is complex. For thin data-access services, the ceremony of ports and adapters is overhead — a simple layered structure suffices.

## Economic and Evolutionary Concerns

### Build vs Buy; Managed Services Tradeoff
**What.** Choosing between implementing a component yourself and using a vendor/managed service.
**Use when.** Every infrastructure decision: database, queue, cache, auth, search.
**Advantages.**
- Buy/managed: faster to start, operational burden on vendor, security patches handled
- Build: full control, no vendor lock-in, potentially cheaper at massive scale
**Tradeoffs.**
- Buy: vendor lock-in, cost at scale, limited customisation, dependency on vendor roadmap
- Build: engineering time, maintenance burden, undifferentiated heavy lifting
**Staff signal.** Build only what differentiates your product. Running your own Kafka cluster is rarely a competitive advantage — but if Kafka's semantics don't fit and you need custom delivery guarantees, building may be justified.

### Migration Patterns
**What.** Techniques for safely moving traffic or data between implementations: dual writes (write to old and new simultaneously), shadow reads (new system reads in parallel, results compared but not served), dark launch (new path exercised under production load without user-visible effect), backfill (populating new store from old), cutover (switching traffic), rollback plan.
**Use when.** Replacing any system component in production.
**Advantages.**
- Each technique mitigates a different risk (correctness, performance, data completeness)
**Tradeoffs.**
- Dual writes risk inconsistency if one write fails; require idempotency and reconciliation
- Shadow reads add load to both systems during the comparison period
**Staff signal.** Never plan a migration without a rollback strategy. The rollback must be tested before the cutover — an untested rollback is not a rollback, it's a hope.

### Data Migration: Expand-Contract (Parallel Change)
**What.** A three-phase schema migration: (1) Expand — add new column/table alongside old; code writes to both. (2) Migrate — backfill existing data from old to new shape. (3) Contract — remove old column/code path once all readers use the new shape.
**Use when.** Changing schemas in systems that cannot tolerate downtime.
**Advantages.**
- Zero-downtime schema evolution; rollback is possible at each phase
- Decouples schema change from code deployment
**Tradeoffs.**
- Slow: each phase requires a separate deployment; total migration spans days/weeks
- Dual-write code adds complexity and must handle both shapes simultaneously
**Staff signal.** The expand phase is the critical safety net — if the new shape has problems, you still have the old column. Skipping expand and doing a destructive rename is the most common cause of migration-related outages.

### Versioning and Compatibility
**What.** Managing change across service boundaries without breaking consumers. Strategies include additive-only changes (backward compatible), semantic versioning, URL path versioning, header-based versioning, and consumer-driven contract testing.
**Use when.** Any API that has more than one consumer or cannot be deployed atomically with its callers.
**Advantages.**
- Backward-compatible changes allow independent deployment
**Tradeoffs.**
- Supporting multiple versions simultaneously increases maintenance cost
- Breaking changes require coordinated migration (deprecation period, client updates)
**Staff signal.** Prefer evolution over versioning: add fields, never remove or rename. If you must break, use expand-contract at the API level — deploy the new endpoint, migrate consumers, then remove the old one.

### Technical Debt and Evolvability
**What.** Accumulated design shortcuts that increase future change cost. Evolvability is the architectural property of remaining changeable over time.
**Use when.** Prioritising engineering investment; arguing for platform work in design reviews.
**Advantages.**
- Conscious debt with a repayment plan accelerates short-term delivery
**Tradeoffs.**
- Unmanaged debt compounds: each feature takes longer; incident rate increases
**Staff signal.** In interviews, frame debt as a tradeoff, not a failure. The staff-level insight is distinguishing deliberate debt (known shortcut with plan) from accidental debt (didn't know better) and reckless debt (knew and didn't care).

### Cost as an Architectural Constraint
**What.** Treating infrastructure cost as a first-class design input. Unit economics (cost per request, cost per user, cost per GB stored) guide architectural choices.
**Use when.** Designing at scale where infrastructure spend is material; evaluating serverless vs container vs bare-metal.
**Advantages.**
- Prevents architectures that are technically elegant but economically unviable
**Tradeoffs.**
- Optimising solely for cost can sacrifice reliability or developer productivity
**Staff signal.** A strong answer in a design interview includes a cost dimension: "At 10K RPS this would cost approximately $X/month on managed service Y, which justifies building our own at 100K RPS." Napkin math on cost is a staff-level differentiator.

## Common interview traps

- Proposing microservices for a brand-new product with unclear domain boundaries — start with a modular monolith.
- Ignoring the database when describing "independent deployment" — shared databases negate service independence.
- Treating CQRS and event sourcing as the same thing — CQRS is about separate models; event sourcing is about persistence strategy. They combine well but are independent.
- Describing a saga without mentioning compensation or idempotency.
- Using "eventual consistency" without explaining what the user sees during the inconsistency window and how the system handles it.
- Proposing a service mesh for a system with three services — the overhead isn't justified.
- Forgetting cold-start latency when recommending serverless for latency-sensitive paths.
- Designing autoscaling on CPU for a workload that's I/O-bound or memory-bound.
- Presenting "strangler fig" without addressing the shared-data problem.
- Treating "build vs buy" as a purely technical decision — ignoring team size, hiring, and maintenance runway.

## Drill questions

1. You have a monolith with 60 engineers. What signals tell you it's time to extract services, and what do you extract first?
2. Two services need transactional consistency across their data. What are your options and when does each apply?
3. Describe how you'd migrate a payment table from one schema to another with zero downtime and a rollback plan.
4. A team added CQRS but users complain about stale reads. What design options resolve this without sacrificing the benefits?
5. Your choreographed event flow has a bug where orders occasionally get stuck mid-process. How do you detect, debug, and fix this?
6. When does serverless become more expensive than a container fleet, and how would you model the crossover point?
7. A service mesh adds 3 ms of latency per hop in a 5-hop call chain. What architectural changes reduce end-to-end latency?
8. You're designing a multi-tenant SaaS. Should the "tenant" service be its own microservice or a module? Justify either answer.
9. How does the inverse Conway manoeuvre influence your decision to split a service?
10. Your autoscaler keeps oscillating (scaling up then immediately down). What's likely wrong and how do you fix it?
11. Explain why dual writes are dangerous and what alternatives exist for migration.
12. A distributed monolith has emerged. What are three concrete symptoms and how would you remediate?
