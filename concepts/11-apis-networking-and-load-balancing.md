# 11. APIs, Networking & Load Balancing

This area covers how services expose their capabilities to clients and to each other, how traffic is routed and balanced across replicas, and the network fundamentals that constrain all of it. Mastery here means knowing which protocol, which balancing strategy, and which API style matches the access pattern — and articulating the failure modes of each choice.

## Quick reference

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| L4 vs L7 load balancer | Route by connection vs by request content | Choosing between throughput and routing intelligence |
| Power-of-two-choices | Near-optimal balancing with minimal state | Need better than round-robin without full state |
| Consistent hashing LB | Affinity without stickiness rigidity | Caching tier or stateful-session routing |
| Health checks | Detect and remove unhealthy backends | Any load-balanced pool |
| gRPC / Protobuf | Strongly-typed, efficient inter-service RPC | Internal service-to-service with streaming needs |
| GraphQL | Client-driven query shape | Mobile clients with varied data needs |
| Cursor pagination | Stable, performant page traversal | Any list endpoint over mutable data |
| Idempotency keys | Safe client retries for non-idempotent ops | Payment, order creation, or any mutating API |
| WebSockets | Full-duplex persistent connection | Real-time bidirectional communication |
| SSE | Server-to-client streaming over HTTP | Live feeds, notifications (unidirectional) |
| Fan-out on write vs read | Pre-compute vs on-demand assembly | Social feeds, timelines, notification systems |
| Service discovery | Locate available instances dynamically | Microservice deployments with elastic scaling |
| DNS-based LB | Distribute at resolution time | Global traffic management, geo-routing |

## Networking Foundations

### Relevant OSI/TCP-IP Layers
**What.** In system design, three layers dominate discussion: L3 (IP — routing, anycast), L4 (TCP/UDP — port-based multiplexing, connection semantics), L7 (HTTP/gRPC — request content, headers, paths). Everything between is abstracted away in practice.
**Use when.** Choosing where to terminate TLS, where to load-balance, and what information is available for routing decisions at each layer.
**Advantages.**
- L4 decisions are cheap (kernel-space, per-connection, ~millions of concurrent connections on commodity hardware)
- L7 decisions are rich (can route by URL path, header, cookie, request body)
**Tradeoffs.**
- L7 load balancers must terminate TLS, parse HTTP, and maintain per-request state — significantly higher CPU cost per connection
- L4 cannot inspect encrypted payloads without termination
**Staff signal.** In practice you often chain both: an L4 layer (e.g., AWS NLB, IPVS) for raw connection distribution, fronting an L7 layer (Envoy, Nginx) for intelligent routing.

### TCP vs UDP; QUIC and HTTP/3
**What.** TCP provides reliable, ordered byte streams with congestion control. UDP is unreliable, unordered, but avoids head-of-line (HOL) blocking. QUIC (the transport under HTTP/3) runs over UDP, provides per-stream flow control, built-in TLS 1.3, and 0-RTT connection resumption.
**Use when.** TCP for most application protocols. UDP for latency-sensitive use cases (gaming, real-time video). QUIC/HTTP3 when you need multiplexed streams without TCP's HOL blocking.
**Advantages.**
- QUIC eliminates TCP HOL blocking: a lost packet in one stream doesn't stall other streams
- 0-RTT resumption eliminates one round-trip for repeat connections
**Tradeoffs.**
- QUIC is still maturing in middlebox/firewall support; some networks block or throttle UDP
- HTTP/2 over TCP still suffers HOL at the TCP layer even though HTTP/2 multiplexes at the application layer — this is the specific failure that motivated HTTP/3
**Staff signal.** Explain both levels of HOL blocking: TCP-level (one lost segment blocks all streams sharing the connection) and HTTP/2-level (solved by HTTP/2's multiplexing but still present at TCP). HTTP/3 solves both.

### TLS Handshake and mTLS
**What.** TLS 1.3 requires one round-trip for a fresh connection (down from two in TLS 1.2). Session resumption (tickets or PSK) enables 0-RTT. Mutual TLS (mTLS) additionally authenticates the client's identity to the server via client certificates.
**Use when.** mTLS for zero-trust service meshes (Istio, Linkerd) where every service verifies its peers. Session resumption for latency-sensitive high-connection-rate clients.
**Advantages.**
- mTLS removes the need for application-layer service authentication tokens between internal services
- 0-RTT eliminates handshake latency for returning clients
**Tradeoffs.**
- mTLS requires certificate distribution, rotation, and revocation infrastructure (complexity cost)
- 0-RTT is vulnerable to replay attacks — only safe for idempotent requests
**Staff signal.** Certificate rotation at scale (thousands of services) is the operational bottleneck of mTLS, not the cryptographic overhead. Short-lived certificates (hours, not years) with automated issuance (SPIFFE/SPIRE) is the modern solution.

### DNS Resolution and Its Limits
**What.** Clients resolve domain names through recursive resolvers that cache responses according to the record's TTL. DNS-based load balancing returns multiple A/AAAA records or uses weighted/geolocation routing (Route 53, Cloud DNS).
**Use when.** Global traffic steering across regions; coarse-grained failover.
**Advantages.**
- Zero infrastructure cost on the data path — resolution happens once per TTL
- Geo-DNS directs users to the nearest region without any proxy layer
**Tradeoffs.**
- Client and recursive-resolver caching means DNS changes propagate slowly (even with low TTLs, many resolvers enforce minimums of 30–300 s)
- No per-request intelligence; granularity is per-resolution, not per-connection
**Staff signal.** DNS-based failover has a "long tail of staleness" — some clients hold stale records for minutes after a failover. Design systems to tolerate both old and new resolutions being active simultaneously.

### Anycast Routing
**What.** Multiple geographically distributed nodes advertise the same IP address via BGP. Routers direct packets to the nearest (in network-hop terms) instance.
**Use when.** CDN edge nodes, DNS resolvers (e.g., 1.1.1.1, 8.8.8.8), DDoS scrubbing.
**Advantages.**
- Automatic nearest-node routing without client-side intelligence
- Inherent DDoS resilience — attack traffic is distributed across all announcing nodes
**Tradeoffs.**
- BGP route changes can shift a client to a different node mid-connection (problematic for TCP; fine for UDP/DNS)
- Debugging is harder because the same IP resolves to different hosts depending on vantage point
**Staff signal.** Anycast works naturally for stateless or connection-brief protocols (DNS, initial TLS handshake) but must be paired with connection-migration mechanisms (like QUIC's connection IDs) for long-lived stateful connections.

## Load Balancing

### L4 vs L7 Load Balancers
**What.** L4 balancers (NLB, IPVS, Maglev) route at the connection level based on IP/port tuples without inspecting payload. L7 balancers (ALB, Envoy, Nginx, HAProxy) parse application-layer data and can route based on URL, headers, cookies, or gRPC method.
**Use when.** L4 when you need raw throughput and minimal latency overhead. L7 when you need content-based routing, header injection, or per-request observability.
**Advantages.**
- L4: handles millions of connections with minimal CPU; transparent to protocol
- L7: enables canary deployments, A/B routing, request-level retries, and observability injection
**Tradeoffs.**
- L7 must terminate TLS (adds CPU) and maintain per-request state (adds memory)
- L4 cannot distinguish between healthy and unhealthy request patterns within a connection
**Staff signal.** Modern service meshes (Envoy sidecars) act as per-pod L7 balancers for east-west traffic, giving you L7 routing intelligence without a centralized L7 bottleneck.

### Load Balancing Algorithms
**What.** Round-robin: simple rotation. Weighted RR: proportional to declared capacity. Least-connections: route to the backend with fewest active connections. Least-response-time: factor in observed latency. Random: stateless. Power-of-two-choices (P2C): pick two random backends, send to the one with fewer connections. Consistent hashing: affinity by request attribute. IP-hash: session affinity by source IP.
**Use when.** Least-connections for heterogeneous backends. P2C for large pools where full state is impractical. Consistent hashing when backend-local caching benefits from affinity.
**Advantages.**
- P2C achieves O(log log N) max load with only local (two-sample) information — exponentially better than random's O(log N) — with near-zero coordination cost
**Tradeoffs.**
- Least-connections requires the balancer to track all active connections (state proportional to backend count)
- Consistent hashing sacrifices balance for affinity: hot keys still overload one node
**Staff signal.** P2C is disproportionately effective because of the "power of two choices" phenomenon: even choosing the better of just two random options collapses the maximum load from Θ(log N / log log N) to Θ(log log N). Google's Maglev and Envoy both use P2C variants in production.

### Health Checks
**What.** Active checks: the load balancer periodically probes backends (TCP connect, HTTP GET /health). Passive checks: the balancer observes real traffic failures to detect unhealthy backends. Shallow checks verify the process is listening; deep checks verify downstream dependencies (DB connectivity, disk space).
**Use when.** Any load-balanced pool — always configure health checks.
**Advantages.**
- Removes failed backends from the pool before clients experience errors
- Deep checks prevent routing traffic to a backend that is "up" but unable to serve (e.g., lost DB connection)
**Tradeoffs.**
- Deep checks can cause cascading removal: if a shared dependency is down, all backends fail their checks simultaneously, leaving zero capacity
- Flapping: a backend oscillates between healthy/unhealthy, causing repeated draining and re-addition
**Staff signal.** The solution to cascading deep-check failure is "failing open": if more than X % of backends fail simultaneously, assume the check itself is wrong and keep backends in the pool. This is the opposite of the default (fail-closed) behaviour, and interviewers reward candidates who identify when each mode is appropriate.

### Sticky Sessions
**What.** The load balancer routes all requests from the same client to the same backend, typically via a cookie or IP hash.
**Use when.** Legacy applications that store session state in local memory and cannot be refactored to externalise state.
**Advantages.**
- Avoids session-store infrastructure for simple applications
**Tradeoffs.**
- Undermines horizontal elasticity: new backends receive no existing sessions, and draining a backend requires session migration or loss
- Hot backends cannot be relieved by adding capacity (existing sessions are pinned)
**Staff signal.** The principled solution is to externalise session state (Redis, database) so any backend can serve any request. Sticky sessions are a workaround, not an architecture.

### Connection Pooling and Draining
**What.** Connection pooling: clients and proxies maintain a pool of pre-established connections to backends to avoid per-request TCP/TLS handshake cost. Connection draining (graceful shutdown): a backend being removed stops accepting new connections but finishes in-flight requests before terminating.
**Use when.** Pooling: always for inter-service communication. Draining: any rolling deployment or scaling event.
**Advantages.**
- Pooling reduces latency by ~1–3 ms per request (TCP + TLS handshake savings)
- Draining eliminates connection-reset errors during deploys
**Tradeoffs.**
- Over-large pools can exhaust backend file descriptors; under-sized pools become bottlenecks
- Long drain timeouts slow down deploy velocity
**Staff signal.** In Kubernetes, the pod shutdown sequence (preStop hook → SIGTERM → terminationGracePeriodSeconds) must align with the load balancer's health-check interval to avoid routing traffic to a pod that has already begun shutting down.

## API Design

### REST Principles
**What.** Resources identified by URIs, manipulated via standard HTTP verbs (GET, POST, PUT, PATCH, DELETE). Statelessness: each request carries all information needed. HATEOAS: responses include hypermedia links to related actions.
**Use when.** Public APIs, CRUD-heavy services, when broad tooling and cacheability matter.
**Advantages.**
- HTTP caching works natively with GET semantics
- Ubiquitous client and tooling support
**Tradeoffs.**
- Over-fetching (returns fields the client doesn't need) and under-fetching (requires multiple calls to assemble a view)
- HATEOAS is rarely implemented in practice; most "REST" APIs are actually HTTP RPC
**Staff signal.** Idempotency by method: GET, PUT, DELETE are idempotent by specification; POST is not. A well-designed API makes POST idempotent via explicit idempotency keys (see below), not by relying on clients to never retry.

### gRPC and Protocol Buffers
**What.** gRPC is a high-performance RPC framework using HTTP/2 for transport and Protocol Buffers for serialisation. Supports unary, server-streaming, client-streaming, and bidirectional-streaming RPC.
**Use when.** Internal service-to-service communication where strong typing, code generation, streaming, and binary efficiency matter more than browser compatibility.
**Advantages.**
- Protobuf messages are 3–10× smaller than equivalent JSON; serialisation/deserialisation is ~5–10× faster
- Streaming RPC enables real-time data flows without WebSocket plumbing
**Tradeoffs.**
- Not browser-native (requires grpc-web proxy); harder to debug with curl
- Schema evolution requires care: removing or renaming fields can break backward compatibility
**Staff signal.** gRPC multiplexes over a single HTTP/2 connection; this means a slow RPC can head-of-line-block faster RPCs on the same connection at the TCP level. Mitigation: multiple connections or HTTP/3.

### GraphQL
**What.** A query language where the client specifies exactly which fields it needs in a single request, solving REST's over/under-fetching problem. The server resolves the query by invoking resolvers per field.
**Use when.** Client applications (especially mobile) with diverse data needs that would otherwise require many REST endpoints or versioned views.
**Advantages.**
- Eliminates multiple round-trips: one request fetches exactly the needed shape
- Introspection and strong typing enable powerful developer tooling
**Tradeoffs.**
- N+1 resolver problem: naive resolution of a list triggers one DB query per item (mitigated by DataLoader batching)
- Caching is hard: responses are client-specific shapes, so HTTP caching is ineffective; requires application-level cache keying
- Unbounded query depth enables denial-of-service; must implement query cost analysis and depth limiting
**Staff signal.** GraphQL moves complexity from many endpoints to one flexible endpoint, but that single endpoint must now handle arbitrary complexity. Query cost estimation (assigning weights to fields and imposing per-request budgets) is essential for production safety.

### API Versioning
**What.** Strategies to evolve APIs without breaking existing clients: URI path versioning (/v1/users), custom header (Api-Version: 2), content negotiation (Accept: application/vnd.myapi.v2+json).
**Use when.** Any API with external consumers that cannot be updated in lockstep with the server.
**Advantages.**
- URI versioning is explicit and easily understood; simplest to implement
- Header-based allows the same URL to serve multiple versions (cleaner caching)
**Tradeoffs.**
- URI versioning duplicates routes and can lead to code duplication if not carefully structured
- All strategies require a deprecation policy with timelines and sunset headers
**Staff signal.** The superior long-term approach: design APIs to be backward-and-forward compatible from day one (additive-only changes, optional fields, never remove or rename) so that versioning is needed only for breaking structural changes.

### Pagination: Offset vs Cursor
**What.** Offset/limit: `SELECT ... LIMIT 20 OFFSET 100`. Cursor/keyset: `SELECT ... WHERE id > :last_seen_id ORDER BY id LIMIT 20`.
**Use when.** Cursor for any production paginated endpoint over mutable data. Offset only for admin/internal UIs where simplicity trumps correctness.
**Advantages.**
- Cursor is O(1) with an index seek (regardless of page depth); offset is O(N) because the DB must scan and discard N rows
- Cursor is stable under concurrent writes: inserts/deletes don't cause duplicates or skipped items
**Tradeoffs.**
- Cursor doesn't support "jump to page 5" — only sequential traversal
- Requires a unique, orderable column (or composite) for the cursor value
**Staff signal.** Offset degrades quadratically with depth (page 1000 scans 20,000 rows to discard 19,980) and is unstable: if a row is inserted before the current offset, the next page duplicates an item. Always recommend cursor/keyset for client-facing paginated APIs.

### Idempotency Keys
**What.** A client-generated unique token (UUID) sent with a mutating request. The server stores the result keyed by this token; retries with the same key return the stored result without re-executing the operation.
**Use when.** Any non-idempotent operation that clients may retry due to timeouts or network errors: payments, order placement, resource creation.
**Advantages.**
- Makes retries safe without requiring the client to know whether the first attempt succeeded
- Decouples retry safety from API semantics
**Tradeoffs.**
- Requires server-side storage of idempotency records with appropriate TTL
- Must handle the "in-progress" case: a retry arrives while the first request is still executing
**Staff signal.** Stripe's idempotency implementation stores the response and replays it byte-for-byte on retry, including error responses — this ensures clients see deterministic behaviour regardless of retry timing.

## Real-Time Communication

### Long Polling, SSE, WebSockets, Webhooks
**What.** Long polling: client sends a request; server holds it open until data is available, then responds. SSE (Server-Sent Events): unidirectional server-to-client stream over HTTP. WebSockets: full-duplex bidirectional persistent connection upgraded from HTTP. Webhooks: server calls a client-provided URL when an event occurs.
**Use when.** Long polling for simple notification with wide compatibility. SSE for live feeds/dashboards. WebSockets for chat, gaming, collaborative editing. Webhooks for asynchronous event delivery to external systems.
**Advantages.**
- SSE is simpler than WebSockets (HTTP-native, auto-reconnect, works through most proxies)
- WebSockets enable true bidirectional real-time communication
**Tradeoffs.**
- WebSocket connections are stateful, which complicates horizontal scaling (need sticky routing or a pub/sub backplane)
- Webhooks shift reliability burden to the receiver: the sender must implement retry, dead-letter, and delivery guarantees
**Staff signal.** For unidirectional server→client use cases (notifications, live scores), SSE is almost always preferable to WebSockets: simpler, HTTP-compatible, and auto-reconnects. WebSockets are justified only when the client also needs to send frequent messages to the server.

### Fan-Out on Write vs Fan-Out on Read
**What.** Fan-out on write: when a user publishes content, immediately write it to all followers' timelines (pre-compute). Fan-out on read: when a user opens their timeline, assemble it on-demand by querying all followed users' posts.
**Use when.** Social media feeds, notification systems, activity streams.
**Advantages.**
- Fan-out on write: reads are O(1) — just fetch the pre-computed timeline; low read latency
- Fan-out on read: writes are O(1) — no fanout cost; storage-efficient
**Tradeoffs.**
- Fan-out on write is expensive for users with millions of followers (celebrity problem); a single post triggers millions of writes
- Fan-out on read is expensive at read time for users following many accounts
**Staff signal.** The hybrid approach (Twitter's actual architecture): fan-out on write for normal users; for celebrities (>500 K followers), skip pre-computation and merge their posts into followers' timelines at read time. This caps both write amplification and read latency.

## Service Infrastructure

### Reverse Proxy vs Forward Proxy vs API Gateway
**What.** Forward proxy: sits in front of clients, masking their identity (e.g., corporate proxy). Reverse proxy: sits in front of servers, handling TLS termination, caching, compression (Nginx, HAProxy). API gateway: a specialized reverse proxy that adds authentication, rate limiting, request transformation, and routing (Kong, Apigee, AWS API Gateway).
**Use when.** Reverse proxy for any web-facing service. API gateway when you need centralised cross-cutting concerns for a microservice fleet.
**Advantages.**
- Centralises TLS, auth, rate limiting — avoids duplicating this logic in every service
**Tradeoffs.**
- API gateway becomes a single point of failure and a deployment bottleneck if too much logic accrues there
- A "smart gateway, dumb services" pattern inverts ownership and slows teams
**Staff signal.** The gateway should handle protocol translation and policy enforcement only. Business logic in the gateway creates a distributed monolith — a common anti-pattern at scale.

### Service Discovery
**What.** Client-side discovery: each client queries a service registry (Consul, etcd, ZooKeeper) to find available instances and load-balances locally. Server-side discovery: clients send to a fixed endpoint (load balancer) which consults the registry internally.
**Use when.** Any microservice architecture with dynamic instance counts.
**Advantages.**
- Client-side eliminates the LB as a bottleneck/SPOF and enables per-client routing intelligence
- Server-side is simpler for clients (no SDK needed)
**Tradeoffs.**
- Client-side couples every service to the registry SDK and health-check logic
- Server-side adds an extra network hop
**Staff signal.** Modern service meshes (Istio/Envoy) combine both: client-side discovery is performed by the sidecar proxy transparently — the application thinks it's talking to localhost while the sidecar handles discovery, balancing, and retries.

### North-South vs East-West Traffic
**What.** North-south: traffic entering or leaving the cluster boundary (external clients to internal services). East-west: traffic between internal services within the cluster.
**Use when.** Reasoning about where to place security controls, load balancers, and observability.
**Advantages.**
- Distinguishing the two clarifies where to apply different TLS policies, rate limiting, and authorization
**Tradeoffs.**
- In microservice architectures, east-west traffic volume often dwarfs north-south by 10–100×, yet teams over-invest in ingress security and under-invest in internal encryption/auth
**Staff signal.** A common blind spot: teams secure the front door (north-south with WAF, rate limiting, authentication) but leave east-west traffic unauthenticated. Service meshes with mTLS address this, but at operational cost.

## Common interview traps

- Saying "use REST" without justifying why REST over gRPC for the specific use case (internal vs external, streaming needs).
- Choosing WebSockets for a unidirectional feed where SSE would be simpler and more robust.
- Describing round-robin load balancing without noting it fails with heterogeneous backends or variable request costs.
- Forgetting that DNS-based failover is slow due to client-side caching; assuming TTL=30 s means all traffic shifts in 30 s.
- Proposing offset pagination for a user-facing API over a frequently-mutated dataset.
- Ignoring the celebrity problem when describing fan-out on write for a social network.
- Designing an API gateway that accumulates business logic — failing to identify the distributed monolith risk.
- Assuming HTTP/2 solves head-of-line blocking completely (it doesn't — TCP HOL remains).

## Drill questions

1. Your L7 load balancer uses round-robin. One backend is 2× slower due to a noisy neighbour. What happens to overall latency? Which algorithm would self-correct?
2. Explain why power-of-two-choices achieves exponentially better max-load than purely random assignment, using only two samples per decision.
3. A user with 10 million followers posts. Describe the tradeoffs of fan-out on write vs read for this event. What hybrid would you propose?
4. Your paginated API uses offset/limit. A user is on page 50 and another user deletes a record on page 1. What does the user on page 50 experience? How does cursor pagination avoid this?
5. A backend is oscillating between healthy and unhealthy every 5 seconds. Your health check interval is 3 seconds with a threshold of 2 consecutive failures. Describe the flapping behaviour and how to mitigate it.
6. Your service communicates via gRPC over a single HTTP/2 connection. One RPC takes 30 seconds. What happens to other RPCs? What transport-layer mechanism causes this?
7. You're designing a payment API. A client's POST times out. The client retries. Without idempotency keys, what can go wrong? With them, describe the server-side implementation.
8. Your API gateway handles auth, rate limiting, routing, request transformation, response aggregation, and circuit breaking. What's the architectural risk, and how would you mitigate it?
9. Contrast SSE and WebSockets for a stock-price ticker. Which would you choose and why?
10. When would you choose client-side service discovery over server-side, and what is the primary disadvantage?
