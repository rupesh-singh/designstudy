# 10. Caching, CDN & Content Delivery

Caching exploits temporal and spatial locality to serve repeated or predictable requests from fast storage rather than recomputing or re-fetching them. Because real-world access patterns follow power-law (Zipfian) distributions — a small fraction of keys absorb the vast majority of reads — even modest cache sizes yield outsized hit rates. The critical arithmetic: if your cache absorbs 90 % of requests, origin sees 10 % of traffic; improving to 95 % means origin now sees only 5 % — half the load — for just five percentage points of hit-rate gain. This non-linearity is why caching dominates performance optimisation at scale.

## Quick reference

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Cache-aside | Application fetches from cache, fills on miss | Default choice for read-heavy services |
| Read-through | Cache itself fetches from source on miss | Want simpler app code with a smart cache layer |
| Write-through | Every write goes to cache and store synchronously | Need strong consistency between cache and storage |
| Write-behind | Writes go to cache; async flush to store | Write-heavy workloads tolerant of brief data-loss risk |
| Write-around | Writes go directly to store, bypassing cache | Data written once, rarely re-read soon after |
| Refresh-ahead | Proactively reload keys before expiry | Latency-sensitive paths with predictable hot keys |
| LRU / LFU / W-TinyLFU | Eviction policies | Choose based on scan resistance vs frequency needs |
| TTL jitter | Randomise expiry across keys | Prevent mass simultaneous expiration (avalanche) |
| Cache stampede mitigations | Request coalescing, locks, early recompute | High-traffic keys with expensive regeneration |
| Negative caching | Cache the absence of a key | Protect against repeated lookups for non-existent data |
| Consistent hashing | Distribute keys across cache nodes | Minimise redistribution when nodes join/leave |
| CDN / Edge cache | Serve content from geographically close nodes | Static assets, media, or cacheable API responses at global scale |
| HTTP caching semantics | Browser/proxy caching via headers | Any content served over HTTP |

## Cache Topology

### Cache Layers
**What.** A production system typically stacks multiple caching tiers: browser/client cache, CDN edge, reverse proxy (e.g., Nginx), application-level local cache (in-process), distributed cache (Redis/Memcached), database buffer pool, and materialised views. Each layer has different latency, capacity, and consistency characteristics.
**Use when.** Designing any system serving reads at scale; understanding which tier to optimise first depends on where the majority of misses originate.
**Advantages.**
- Each layer absorbs a fraction of misses from the layer above, multiplicatively reducing origin load
- Local caches avoid network round-trips entirely (~100 ns vs ~1 ms for distributed cache)
**Tradeoffs.**
- More layers means more invalidation surfaces — consistency becomes harder
- Debugging stale data requires knowing which layer served a stale copy
**Staff signal.** When invalidating across tiers, you must invalidate from the lowest (closest to origin) tier outward; otherwise an upper tier re-fills from a stale lower tier before the lower tier is purged.

## Read Patterns

### Cache-Aside (Lazy Loading)
**What.** The application checks the cache first; on a miss it reads the source, then writes the result into cache. The cache is unaware of the data store.
**Use when.** General-purpose read caching. Used by virtually every web application layer backed by Memcached or Redis.
**Advantages.**
- Only actually-requested data occupies cache memory
- Cache failure doesn't block reads — app falls through to origin
**Tradeoffs.**
- First request for any key incurs full latency (cold-start penalty)
- Race condition: two concurrent misses can both fetch and write, potentially inserting a stale version if a write occurred between the two reads
**Staff signal.** The classic race: Thread A misses, Thread B misses, Thread B writes to DB, Thread A fills cache with the old value. Mitigation: use a conditional SET (e.g., Redis SET NX with a version) or accept brief staleness.

### Read-Through Cache
**What.** The cache itself is configured with a loader function; on a miss it fetches from the backing store transparently. The application interacts only with the cache interface.
**Use when.** You want a uniform read API and the cache library supports loaders (e.g., Guava LoadingCache, Caffeine in Java).
**Advantages.**
- Simplifies application code — no manual fill logic
- Cache can internally deduplicate concurrent loads for the same key (coalescing built in)
**Tradeoffs.**
- Couples cache lifecycle to data-store access patterns
- Errors from the backing store surface through the cache layer, complicating error handling
**Staff signal.** Read-through with request coalescing effectively solves stampede at the library level — but only within one process; distributed stampede still needs external coordination.

## Write Patterns

### Write-Through Cache
**What.** On every write, data is written to both the cache and the persistent store synchronously before acknowledging the caller.
**Use when.** You need the cache to always reflect the latest committed state and can tolerate the latency of a synchronous dual-write.
**Advantages.**
- Cache is never stale with respect to committed writes (strong consistency)
- Simplifies read logic — reads always trust the cache
**Tradeoffs.**
- Write latency increases (two writes on the critical path)
- Wastes cache space on data that may never be read (write-heavy, read-cold keys)
**Staff signal.** Write-through only guarantees consistency if the cache and store write are atomic or in the same transaction; without that, a crash between the two leaves them diverged.

### Write-Behind (Write-Back) Cache
**What.** Writes are acknowledged after updating the cache; the cache asynchronously flushes dirty entries to the store in batches or after a delay.
**Use when.** Write-heavy workloads where you can tolerate a small window of potential data loss (e.g., session stores, counters, analytics ingestion).
**Advantages.**
- Dramatically lower write latency perceived by callers
- Batching amortises store I/O (fewer round-trips, larger batch inserts)
**Tradeoffs.**
- Data loss window: if the cache node crashes before flush, writes are lost
- Ordering and conflict resolution become complex if multiple nodes write-behind the same keys
**Staff signal.** Write-behind is effectively a WAL in cache RAM — evaluate it the same way you'd evaluate any durability-versus-speed tradeoff. Pair with replication if data loss is unacceptable.

### Write-Around Cache
**What.** Writes go directly to the persistent store and do not populate or update the cache. The cache is only filled on subsequent reads.
**Use when.** Data is written once and rarely re-read soon after (e.g., log ingestion, archival writes).
**Advantages.**
- Avoids polluting cache with write-once data that displaces frequently-read entries
**Tradeoffs.**
- Immediate reads after a write will miss and incur full origin latency
**Staff signal.** Combine with explicit cache invalidation (rather than fill) for data that *is* re-read, to prevent serving stale entries written before the latest store update.

### Refresh-Ahead (Proactive Refresh)
**What.** The cache proactively reloads entries that are predicted to be needed again before their TTL expires, typically when a read occurs within a configurable window near expiry.
**Use when.** Latency-sensitive hot keys with predictable access (e.g., product catalogue pages, feature flags).
**Advantages.**
- Eliminates cache-miss latency on the critical path for popular keys
- Smooths load on the origin by spreading refreshes over time
**Tradeoffs.**
- Wasted refresh work if prediction is wrong (key not accessed again)
- Complexity in tuning the refresh window
**Staff signal.** Probabilistic early expiration (à la "XFetch" algorithm) is a stateless variant: each reader independently decides with probability p whether to recompute early, preventing stampede without coordination.

## Eviction & Expiry

### Eviction Policies
**What.** When cache capacity is exhausted, an eviction policy determines which entry to discard. Common policies: LRU (least recently used), LFU (least frequently used), FIFO, ARC (adaptive replacement — balances recency and frequency), W-TinyLFU (windowed admission filter + LFU main space), random eviction.
**Use when.** Every bounded cache requires one; the choice depends on workload characteristics.
**Advantages.**
- LRU: simple, good for recency-dominated workloads; O(1) with a doubly-linked list + hash map
- W-TinyLFU (used by Caffeine): near-optimal hit rates across diverse workloads with low overhead
**Tradeoffs.**
- LRU is scan-vulnerable: a single sequential scan evicts the entire working set (e.g., a full-table analytic query pollutes the cache)
- LFU can entrench old popular keys that are no longer relevant (frequency inertia)
**Staff signal.** If your workload includes periodic full-scans alongside point lookups, LRU is the wrong choice. ARC or W-TinyLFU provide scan resistance by distinguishing one-hit wonders from truly frequent items.

### TTL Strategies and Jitter
**What.** Time-to-live determines how long a cached entry is considered valid. Absolute TTL counts from insertion; sliding TTL resets on each access. TTL jitter adds a random offset to each key's expiry time.
**Use when.** Every cached entry should have a TTL — infinite TTL means you've moved the consistency problem to "never", which is rarely acceptable.
**Advantages.**
- TTL provides an upper bound on staleness without requiring explicit invalidation plumbing
- Jitter prevents cache avalanche (mass coordinated expiry)
**Tradeoffs.**
- Too-short TTLs undermine hit ratio; too-long TTLs increase stale reads
- Sliding TTL can keep infrequently-changing but continuously-accessed data from ever refreshing
**Staff signal.** Apply ±10–20 % random jitter to all TTLs by default. In interview designs, mentioning jitter unprompted signals operational awareness.

## Failure Modes

### Cache Stampede / Thundering Herd
**What.** When a popular key expires, many concurrent requests simultaneously miss and all hit the origin, causing a load spike that can cascade into failure.
**Use when.** Any popular key with expensive recomputation (e.g., a leaderboard, aggregated feed).
**Advantages.**
- Understanding the problem enables targeted mitigations
**Tradeoffs.**
- Mitigations (locks, coalescing) add complexity and latency for the first requester
**Staff signal.** Three complementary mitigations: (1) request coalescing / single-flight — only one goroutine/thread fetches while others wait on a promise; (2) locking — a distributed lock (SET NX with short TTL) ensures one winner; (3) probabilistic early recompute — each reader recomputes with increasing probability as TTL approaches zero, staggering refreshes.

### Cache Penetration
**What.** Requests for keys that will *never* exist in the backing store bypass the cache on every request because there is nothing to fill.
**Use when.** Detecting and mitigating abuse or badly-formed queries that repeatedly ask for absent data.
**Advantages.**
- Negative caching (caching the absence with a short TTL) stops repeated origin hits
- Bloom filters at the cache layer reject provably-absent keys with zero origin cost
**Tradeoffs.**
- Bloom filters consume memory and must be rebuilt when the dataset changes
- Negative-cache entries need short TTLs or explicit invalidation when the key *does* get created
**Staff signal.** Distinguish penetration (non-existent key, possibly adversarial) from stampede (existent key, temporarily absent from cache). Different mitigations apply.

### Cache Avalanche
**What.** A large number of keys expire at the same instant, causing a coordinated miss storm that overwhelms the origin.
**Use when.** You have bulk-loaded cache entries with identical TTLs (common after a cache warm or deploy).
**Advantages.**
- Prevention is straightforward once identified
**Tradeoffs.**
- Requires discipline: every bulk-fill operation must include jitter
**Staff signal.** Avalanche also occurs on cache-node failure in a cluster without replication — all keys on that node become simultaneous misses. Replication or consistent-hashing with virtual nodes limits blast radius.

### Hot Key Problem
**What.** In a distributed cache partitioned by key, an extremely popular key concentrates all traffic on a single shard, saturating its CPU or network.
**Use when.** Celebrity posts, flash sales, viral content — any event that makes one key orders of magnitude hotter than others.
**Advantages.**
- Identifying it early (via shard-level metrics) allows mitigation before failure
**Tradeoffs.**
- Solutions add complexity: local (in-process) cache tier in front of distributed cache, or replicating the hot key to multiple shards with a random suffix
**Staff signal.** The combination of a local L1 cache (short TTL, small capacity) in front of a distributed L2 cache is the standard production mitigation at companies like Twitter and Facebook.

## Distributed Cache Infrastructure

### Consistent Hashing for Cache Clusters
**What.** Keys are mapped to positions on a hash ring; each cache node owns a range. Adding or removing a node redistributes only ~1/N of keys, not all of them.
**Use when.** Any horizontally-scaled cache cluster (Memcached, Redis Cluster ring, or application-level sharding).
**Advantages.**
- Minimises cache invalidation on topology changes (only K/N keys move on average)
- Virtual nodes smooth out load imbalance from poor hash distribution
**Tradeoffs.**
- Doesn't solve hot-key concentration (a hot key still lands on one node regardless of ring size)
- During rebalancing, moved keys produce transient misses
**Staff signal.** Consistent hashing combined with bounded-load (Google's "consistent hashing with bounded loads") can redirect overflow from a saturated node to its ring neighbours, addressing both balance and hot-key scenarios.

### Memcached vs Redis
**What.** Memcached: multi-threaded, pure key-value, no persistence, simple LRU eviction. Redis: single-threaded event loop (with I/O threads since 6.0), rich data structures (sorted sets, streams, HyperLogLog), optional RDB/AOF persistence, Lua scripting, pub/sub, cluster mode with hash-slot partitioning.
**Use when.** Memcached for pure high-throughput simple caching with horizontal scaling. Redis when you need atomic operations on complex data structures, or persistence, or pub/sub alongside caching.
**Advantages.**
- Memcached scales linearly with cores on a single node; simple operational model
- Redis enables patterns (rate limiting via INCR/EXPIRE, leaderboards via sorted sets) that would otherwise need a separate system
**Tradeoffs.**
- Redis single-threaded model means one slow Lua script or KEYS command blocks all clients
- Redis persistence (AOF fsync=always) halves throughput; RDB snapshotting causes fork latency spikes proportional to memory size
**Staff signal.** In interviews, mention that Redis Cluster splits the keyspace into 16,384 hash slots across nodes — you cannot do multi-key operations across slots without hash tags, which can re-introduce hot-slot problems.

## CDN & HTTP Caching

### CDN Architecture
**What.** A content delivery network caches content at edge points-of-presence (PoPs) close to end users. Pull-based CDNs fetch from origin on first miss; push-based CDNs require explicit upload of assets. An origin shield is an intermediate cache layer between edge PoPs and the origin, reducing origin fan-in.
**Use when.** Any content served to geographically distributed users — static assets, video, and even cacheable API responses.
**Advantages.**
- Reduces latency by serving from a PoP tens of milliseconds away instead of hundreds
- Absorbs traffic spikes (flash crowds) without origin scaling
**Tradeoffs.**
- Cache-key design matters: include only relevant dimensions (device, language) or you fragment the cache and destroy hit rates
- Vary header overuse creates combinatorial explosion of cached variants
**Staff signal.** Explain origin shield: without it, 50 PoPs each independently miss and hit origin; with it, all PoPs miss to the shield, which makes a single origin request. This collapses fan-in from O(PoPs) to O(1).

### HTTP Caching Semantics
**What.** Cache-Control directives (max-age, s-maxage, no-store, no-cache, private, public, immutable), ETag/If-None-Match for conditional revalidation, Last-Modified/If-Modified-Since, and stale-while-revalidate (serve stale while asynchronously refreshing).
**Use when.** Any HTTP response — choosing the right headers determines whether browsers, proxies, and CDNs cache effectively.
**Advantages.**
- Immutable + content-hashed URLs (fingerprinting) enables infinite cache lifetime for static assets
- stale-while-revalidate eliminates user-visible latency for near-expiry content
**Tradeoffs.**
- no-cache doesn't mean "don't cache" — it means "always revalidate before use"; misunderstanding this causes bugs
- Private vs public misclassification can leak user-specific data through shared caches
**Staff signal.** A robust static-asset strategy: serve all JS/CSS/images with immutable, max-age=1y under fingerprinted URLs; serve the HTML entry point with no-cache or short max-age so it can reference new fingerprinted assets on deploy.

### Edge Computing
**What.** Running application logic (not just serving cached content) at CDN edge nodes, e.g., Cloudflare Workers, AWS Lambda@Edge, Deno Deploy.
**Use when.** Personalisation, A/B test assignment, auth token validation, or lightweight transformations that benefit from geographic proximity without a full origin round-trip.
**Advantages.**
- Sub-10 ms cold starts in some runtimes; responses from within 50 ms of the user
- Offloads repetitive logic from origin, reducing its compute bill
**Tradeoffs.**
- Limited execution time and memory; no persistent local state
- Debugging distributed edge deployments is significantly harder than centralised services
**Staff signal.** Edge compute is ideal for request routing decisions, geolocation-based content selection, and bot detection — but not for stateful transaction processing, which still requires origin coordination.

## Common interview traps

- Saying "just add a cache" without specifying the invalidation strategy — the interviewer will probe this.
- Confusing cache-aside with read-through; they differ in who is responsible for fetching on miss.
- Forgetting that write-through without atomicity between cache and store can diverge on partial failure.
- Ignoring the cold-start problem: after a deploy or node replacement, the cache is empty and origin takes full load. Mention cache warming.
- Assuming LRU is always correct; failing to note its vulnerability to sequential scans.
- Treating TTL as the *only* invalidation mechanism when explicit invalidation is also needed for correctness.
- Setting identical TTLs on bulk-loaded keys without jitter — this causes avalanche.
- Forgetting the hot-key problem when discussing distributed caches; consistent hashing alone doesn't fix it.
- Confusing no-cache (revalidate every time) with no-store (never cache at all).

## Drill questions

1. Your cache hit ratio is 92 %. Backend can handle 10,000 rps. What is your max total throughput? If you improve to 97 %, what is it now? Show the arithmetic.
2. You have a cache-aside pattern and a concurrent writer. Draw the race condition timeline that produces a stale cache entry. How would you prevent it?
3. Your CDN has 40 PoPs and no origin shield. How many origin requests does a cache miss for a popular object generate? How does an origin shield change this?
4. A developer sets Cache-Control: no-cache, max-age=3600. What actually happens? Is max-age respected?
5. You deploy a new version of your service and the in-memory cache is empty. Traffic is 50,000 rps. Describe what happens and two strategies to mitigate.
6. A product page is accessed 100,000 times per second. Your Redis cluster has 8 shards. Explain why consistent hashing doesn't solve this and what does.
7. When would you choose write-behind over write-through, and what failure scenario must you accept?
8. Explain why going from 95 % to 99 % hit rate is more impactful to origin load than going from 50 % to 80 %, despite the latter being a larger absolute improvement.
9. Your eviction policy is LRU. A nightly analytics job scans the entire dataset. What happens to your cache, and which eviction policy would resist this?
10. How does probabilistic early recomputation prevent stampede without any distributed coordination or locks?
