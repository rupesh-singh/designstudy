# 16. Algorithms, Data Structures & Building Blocks

System design interviews often require knowing the algorithmic primitives that make large-scale systems feasible. These are the building blocks that appear inside databases, caches, load balancers, search engines, and coordination services. Understanding their mechanics, error characteristics, and operational profiles lets you make precise design choices rather than hand-waving.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Consistent hashing | Even distribution with minimal remapping on resize | Distributing data/load across a changing set of nodes |
| Bloom filter | Space-efficient probabilistic set membership | Avoiding expensive lookups for absent keys |
| HyperLogLog | Cardinality estimation with tiny memory | Counting distinct elements at scale |
| Count-Min Sketch | Frequency estimation for heavy hitters | Finding top-K items in streams |
| Reservoir sampling | Uniform random sample from a stream | Sampling when stream size is unknown |
| t-digest / quantile sketches | Mergeable percentile estimation | Aggregating latency percentiles across nodes |
| Merkle tree | Hash-based data verification and sync | Detecting inconsistencies between replicas |
| Skip list | Probabilistic ordered data structure | In-memory sorted key-value (Redis) |
| Trie / radix tree | Prefix search and matching | Autocomplete, IP routing tables |
| Inverted index | Full-text search | Building search engines |
| Vector embeddings / ANN | Similarity search in high-dimensional space | Semantic search, recommendations |
| Geospatial indexing | Location-based queries | Proximity search, map features |
| Distributed ID generation | Globally unique, sortable identifiers | Any distributed system needing unique keys |
| Leader election | Choosing a single coordinator | Consensus, write serialization |
| Gossip protocols | Decentralized state dissemination | Membership, failure detection |
| Rate limiter algorithms | Request admission control | Protecting services from overload |
| Chandy-Lamport | Consistent distributed snapshot | Checkpointing distributed state |
| CRDTs | Conflict-free replicated data types | Multi-master replication without coordination |
| OT vs CRDTs | Real-time collaborative editing | Google Docs-style collaboration |
| Compression algorithms | Space/bandwidth reduction | Storage, network transfer |
| Checksums / hashes | Error detection and integrity | Data verification end-to-end |
| Erasure coding | Fault-tolerant storage with less overhead than replication | Large-scale distributed storage |
| Batching & amortization | Spreading fixed cost across multiple items | Throughput optimization everywhere |
| Backpressure / ring buffers | Flow control under overload | Producers faster than consumers |

## Hashing & Distribution

### Consistent Hashing
**What.** Maps both keys and nodes onto a ring (hash space). Each key is assigned to the next node clockwise on the ring. When a node joins or leaves, only keys in its neighbourhood are remapped — O(K/N) keys move instead of O(K). Virtual nodes (multiple ring positions per physical node) smooth load distribution.
**Use when.** Distributing cache keys (Memcached), partition assignment (DynamoDB, Cassandra), load balancing with sticky sessions.
**Advantages.**
- Adding/removing nodes moves minimal data (proportional to 1/N of total)
- Virtual nodes reduce variance from ~100% to ~5-10% with 100-200 vnodes per node
**Tradeoffs.**
- Without sufficient virtual nodes, load variance between nodes can be extreme
- Hot keys (celebrity problem) still overload a single node regardless of hashing
**Staff signal.** The number of virtual nodes is a tuning parameter: more vnodes = smoother distribution but more metadata (ring membership table). At very large cluster sizes, jump consistent hashing or rendezvous hashing may be preferable for reduced metadata.

## Probabilistic Data Structures

### Bloom Filter
**What.** A bit array of m bits with k hash functions. To add an element, set k bit positions. To query, check if all k positions are set. False positives are possible (all bits set by coincidence); false negatives are impossible.
**Use when.** Avoiding expensive lookups for items not in a set (e.g., LSM-tree databases checking if a key exists before reading SSTables, CDNs checking if content is cached).
**Advantages.**
- Extremely space-efficient: ~10 bits per element gives ~1% false positive rate
- O(k) operations for both insert and query (typically k=7 for 1% FPR)
**Tradeoffs.**
- No deletion (clearing a bit may affect other elements); counting Bloom filters use counters instead of bits but use 4× more space
- False positive rate increases as the filter fills
**Staff signal.** Cuckoo filters support deletion and achieve better space efficiency at low FPR (< 3%). For system design answers, mention cuckoo filters as the modern alternative when deletion is required.

### HyperLogLog
**What.** Estimates the cardinality (count of distinct elements) of a set using ~12 KB of memory regardless of set size. Works by observing the pattern of leading zeros in hash values — more leading zeros implies more distinct elements were hashed.
**Use when.** Counting unique visitors, unique IPs, distinct queries — anywhere exact counting would require unbounded memory.
**Advantages.**
- Fixed memory (~12 KB for standard error of ~0.81%)
- Mergeable: union of two HLLs gives the cardinality of the combined set (essential for distributed systems)
**Tradeoffs.**
- Approximate: standard error ~1.04/√m where m is number of registers (typically 2^14 = 16384)
- Cannot enumerate members or subtract (no intersection directly)
**Staff signal.** Mergeability is the key property for distributed systems: aggregate HLLs from multiple nodes without double-counting. Redis `PFMERGE` uses this. Exact distinct counts across shards would require communicating all elements.

### Count-Min Sketch
**What.** A matrix of counters (d rows × w columns) with d independent hash functions. To increment an element, hash it with each function and increment the corresponding counter in each row. To query frequency, take the minimum across all rows (overestimates due to collisions but never underestimates).
**Use when.** Finding heavy hitters (top-K frequent items) in data streams; detecting trending topics.
**Advantages.**
- Sub-linear space: accuracy controlled by width (w) and depth (d)
- Supports increment and query in O(d) time
**Tradeoffs.**
- Only overestimates, never underestimates — biased toward popular items
- Cannot enumerate all items; must be paired with a heap for top-K
**Staff signal.** In system design, Count-Min Sketch + min-heap is the standard answer for "find the top K items in a stream of billions of events with bounded memory."

### Reservoir Sampling
**What.** Maintains a uniform random sample of size k from a stream of unknown length. When the i-th item arrives (i > k), include it with probability k/i, replacing a random existing sample element.
**Use when.** Sampling from streams (log sampling, A/B test impression sampling) when you don't know the total count upfront.
**Advantages.**
- O(k) memory regardless of stream length; every item has equal probability of inclusion
**Tradeoffs.**
- Cannot parallelise trivially; combining samples from multiple streams requires weighted merging
**Staff signal.** For distributed reservoir sampling, each node maintains its own reservoir, and they're merged using weighted random selection proportional to stream lengths seen by each node.

### t-digest / Quantile Sketches
**What.** A data structure that maintains an approximate distribution summary, enabling percentile queries (p50, p99) with high accuracy at the tails and mergeability across nodes. Works by clustering observed values into centroids with compression favoring the extremes.
**Use when.** Computing latency percentiles across many servers; any case where you need to aggregate distributions without storing all values.
**Advantages.**
- Mergeable across nodes (unlike histograms with misaligned buckets)
- High accuracy at extreme percentiles (p99, p99.9) where it matters most
- Typically ~2-10 KB per digest
**Tradeoffs.**
- Less accurate in the middle of the distribution (by design — tails are prioritized)
- More complex than fixed-bucket histograms
**Staff signal.** This solves the "you can't average percentiles" problem. If you have p99 from 100 servers and need the global p99, you cannot simply average them. t-digests from each server can be merged to produce the correct global percentile. This is why Datadog and other monitoring systems use quantile sketches internally.

## Tree & Graph Structures

### Merkle Trees
**What.** A binary tree where each leaf is a hash of a data block and each internal node is the hash of its children. Any change to data propagates up the tree, so comparing just the root hashes reveals whether two datasets differ. Divergence can be localised by walking down the tree.
**Use when.** Anti-entropy repair (Cassandra, DynamoDB), file integrity verification, blockchain block verification, git tree comparison.
**Advantages.**
- Detects inconsistencies between replicas by exchanging O(log N) hashes
- Pinpoints exactly which data blocks differ without transferring all data
**Tradeoffs.**
- Tree must be rebuilt or incrementally updated when data changes
- Comparison requires tree structure to be aligned (same partitioning)
**Staff signal.** Cassandra uses Merkle trees during repair to identify divergent partitions between replicas. The cost of building the tree is a full data scan — this is why Cassandra repairs are expensive and scheduled during off-peak hours.

### Skip Lists
**What.** A layered linked list with probabilistic balancing. Each element is promoted to higher layers with probability 1/2, creating express lanes for search. Average O(log N) search, insert, delete.
**Use when.** In-memory ordered data structures where balanced trees would work but simpler implementation is preferred.
**Advantages.**
- Simpler implementation than red-black trees with same asymptotic complexity
- Lock-free concurrent implementations are more straightforward than for balanced trees
- Range queries are natural (follow the bottom level after finding start)
**Tradeoffs.**
- Probabilistic: worst case is O(N) though astronomically unlikely
- More pointer overhead than a B-tree for on-disk use
**Staff signal.** Redis uses skip lists for sorted sets because they offer comparable performance to balanced trees with simpler code and efficient range operations. The simplicity advantage matters in production systems where debugging data structure corruption is a real concern.

### Tries and Radix Trees
**What.** A trie stores strings as paths from root to leaf, one character per edge. A radix tree (Patricia trie) compresses chains of single-child nodes into single edges with multi-character labels.
**Use when.** Prefix search (autocomplete), IP routing tables (longest prefix match), DNS lookup.
**Advantages.**
- Prefix search in O(key length) regardless of dataset size
- Radix trees save space by compressing common prefixes
**Tradeoffs.**
- Memory-intensive for large alphabets (each node may have many child pointers)
- Cache-unfriendly due to pointer chasing (vs array-based structures)
**Staff signal.** For autocomplete in interviews, a trie with frequency annotations at nodes (precomputed top-K per prefix) enables O(L) retrieval where L is the prefix length, avoiding sorting at query time.

## Search & Similarity

### Inverted Index
**What.** Maps each term to a posting list (sorted list of document IDs containing that term). The backbone of full-text search engines (Elasticsearch/Lucene). Terms are produced by tokenization (splitting text) and normalization (lowercasing, stemming).
**Use when.** Building search functionality; document retrieval; any keyword-based lookup.
**Advantages.**
- Query time proportional to number of matching documents, not corpus size
- Posting lists support efficient intersection (AND) and union (OR) via merge algorithms
**Tradeoffs.**
- Index size ~30-50% of original data; must be updated on writes
- Relevance ranking (TF-IDF, BM25) requires additional statistics (document frequency, lengths)
**Staff signal.** BM25 is the standard ranking function for text search (used by Elasticsearch by default). It improves over TF-IDF by adding term frequency saturation (diminishing returns for repeated terms) and document length normalization. Understanding this explains why short documents aren't unfairly penalized.

### Vector Embeddings and ANN Search
**What.** Representing items (documents, images, users) as dense vectors in high-dimensional space where distance correlates with semantic similarity. Approximate Nearest Neighbour (ANN) algorithms find similar vectors without exhaustive comparison: HNSW (graph-based, high recall), IVF (partition-based, good for large datasets), product quantization (compresses vectors for memory efficiency).
**Use when.** Semantic search, recommendation systems, image similarity, RAG retrieval for LLMs.
**Advantages.**
- Captures semantic meaning beyond keyword matching
- HNSW achieves >95% recall with ~10× speedup over brute force
**Tradeoffs.**
- Recall vs latency tradeoff: more accurate search is slower
- Index building is expensive (HNSW: O(N log N)); updates require re-indexing or streaming support
- Memory-intensive: 1B vectors × 768 dimensions × 4 bytes = ~3 TB uncompressed
**Staff signal.** Product quantization reduces memory by ~4-8× with ~5% recall loss — essential for billion-scale vector search. The design decision is: HNSW for highest recall with moderate dataset, IVF+PQ for billion-scale with memory constraints. Milvus, Pinecone, and Weaviate combine these.

### Geospatial Indexing
**What.** Structures for efficiently querying spatial data. Geohash: encodes lat/lng into a hierarchical string (prefix = containing region). Quadtree: recursively divides 2D space into four quadrants. R-tree: groups nearby objects into bounding rectangles. S2/H3: hierarchical spherical decomposition into cells.
**Use when.** "Find restaurants within 5 km"; ride-sharing driver matching; geofencing.
**Advantages.**
- Geohash: simple, prefix-based proximity; easy to index in any database (just a string column)
- R-tree: optimal for range queries and spatial joins
- S2/H3: uniform cell sizes on sphere; hierarchical for multi-resolution
**Tradeoffs.**
- Geohash: edge cases at cell boundaries (neighbors may have very different prefixes); non-uniform cell sizes at poles
- R-tree: complex updates; not natively supported in all databases
- Quadtree: uneven depth in non-uniform data distributions
**Staff signal.** The boundary problem with geohash: two points 1 meter apart may have completely different geohash prefixes if they straddle a cell boundary. The solution: always query the target cell plus its 8 neighbors. Uber uses H3 because hexagonal cells have uniform adjacency (every neighbor is equidistant from center).

## Distributed System Primitives

### Distributed Unique ID Generation
**What.** Generating globally unique, sortable identifiers without central coordination. UUIDv4: random, not sortable. UUIDv7/ULID: timestamp-prefixed, lexicographically sortable. Snowflake ID: 64-bit with timestamp + worker ID + sequence.
**Use when.** Primary keys in distributed databases; event ordering; any system needing unique identifiers across multiple nodes.
**Advantages.**
- UUIDv7/ULID: timestamp prefix gives B-tree index locality (sequential inserts cluster together) — UUIDv4's randomness causes page splits and cache misses
- Snowflake: compact 64-bit; sortable; embeds machine identity
**Tradeoffs.**
- Snowflake depends on clock accuracy (clock skew can cause ID collisions or ordering issues)
- UUIDv7: 128 bits may be wasteful for storage; leaks creation time
**Staff signal.** Index locality is a critical performance detail: UUIDv4 as a primary key in B-tree databases (PostgreSQL, MySQL) causes random page writes, increasing I/O amplification by 3-10×. UUIDv7 fixes this by making inserts append-mostly. This alone justifies choosing UUIDv7 over UUIDv4 for any database workload.

### Leader Election
**What.** Selecting a single node to perform a privileged role (accept writes, coordinate). Algorithms: bully (highest-ID wins after failure detected), ring (election token passes around), consensus-based (Raft/Paxos leader is implicitly elected by majority vote).
**Use when.** Single-writer databases, distributed lock services, coordination tasks requiring serialization.
**Advantages.**
- Consensus-based election (Raft) is safe: leader is guaranteed unique per term as long as a majority is reachable
**Tradeoffs.**
- Leader is a potential bottleneck and single point of failure
- Network partitions can cause split-brain without proper fencing (lease-based or epoch-based fencing tokens)
**Staff signal.** A fencing token (monotonically increasing number tied to the lease) prevents a stale leader from corrupting state after partition heals. Without fencing, a slow GC pause can cause a leader to act after its lease expired — this is the core danger of leader election without proper safety.

### Gossip / Epidemic Protocols; SWIM
**What.** Nodes periodically exchange state with random peers; information propagates exponentially like an epidemic. SWIM (Scalable Weakly-consistent Infection-style Membership) is a protocol for membership detection: ping random node, if no ack, ask k others to ping it (indirect probe), then declare suspect/dead.
**Use when.** Cluster membership and failure detection (Cassandra, Consul); disseminating configuration or load information.
**Advantages.**
- Decentralised: no single point of failure; scales O(log N) rounds to propagate
- Robust to message loss (redundant paths)
**Tradeoffs.**
- Eventually consistent: state convergence takes time (seconds to tens of seconds)
- Not suitable for strong-consistency decisions (use consensus for those)
**Staff signal.** SWIM's indirect probing distinguishes between "node is dead" and "network path to me is broken" — reducing false failure detections. Cassandra's failure detector uses a variant of this with an adaptive phi-accrual threshold rather than a fixed timeout.

### Rate Limiter Algorithms
**What.** Token bucket: tokens accumulate at a fixed rate; each request consumes a token; burst capacity = bucket size. Sliding window counter: divides time into windows and counts requests; smooths boundary effects by weighting previous and current window.
**Use when.** API rate limiting, abuse prevention, fairness enforcement.
**Advantages.**
- Token bucket: naturally allows bursts up to bucket capacity while enforcing average rate
- Sliding window counter: memory-efficient (two counters per window) with smooth limiting
**Tradeoffs.**
- Token bucket: requires atomic decrement (Redis MULTI or Lua script for distributed version)
- Fixed window: boundary problem (2× burst at window edges); sliding window fixes this at the cost of slightly more computation
**Staff signal.** In distributed rate limiting, the consistency of the counter matters: eventual consistency means you might exceed the limit by the replication lag × request rate. For strict limits (payment APIs), use a single authoritative counter; for soft limits (general API), approximate distributed counters are acceptable.

### Consistent Snapshotting (Chandy-Lamport)
**What.** An algorithm for capturing a consistent global snapshot of a distributed system without stopping it. Each process records its local state and all messages in transit on incoming channels after receiving a marker message.
**Use when.** Checkpointing distributed streaming systems (Flink uses a variant); debugging distributed state.
**Advantages.**
- No need to stop the system; snapshot is taken concurrently with ongoing processing
**Tradeoffs.**
- Requires FIFO channels (messages arrive in order); adaptation needed for non-FIFO networks
- Snapshot includes in-flight messages, adding complexity to restoration
**Staff signal.** Apache Flink's checkpointing is directly based on Chandy-Lamport: barriers flow through the dataflow graph and each operator snapshots its state upon receiving barriers from all inputs. This enables exactly-once processing semantics with minimal throughput impact.

## Conflict Resolution & Collaboration

### CRDTs
**What.** Data structures designed so that concurrent replicas can be independently updated and merged to a consistent state without coordination. State-based: replicas ship full state and merge via a join-semilattice. Operation-based: replicas ship individual operations that are commutative/idempotent.
**Use when.** Multi-master replication, offline-first applications, collaborative features where strong consistency is too expensive.
**Advantages.**
- Guaranteed convergence without consensus; works across partitions
- G-counter (grow-only), PN-counter (add/subtract), LWW-register (last writer wins), OR-set (observed-remove set), RGA (replicated growable array for sequences)
**Tradeoffs.**
- Metadata growth: tombstones (for deletes) accumulate indefinitely in some CRDTs; OR-set tracks per-element version vectors
- Semantics may surprise users: LWW-register silently discards concurrent writes
- Operation-based CRDTs require reliable causal broadcast
**Staff signal.** The tombstone problem is the operational cost of CRDTs: a set with many add/remove cycles accumulates garbage. Solutions include periodic garbage collection (which requires coordination, partially defeating the purpose) or bounded CRDTs with time-based expiry. In interviews, mentioning this shows you understand the real cost beyond the elegant theory.

### Operational Transformation vs CRDTs for Collaborative Editing
**What.** OT: transforms operations against concurrent edits to preserve intent; requires a central server to order operations. CRDTs (RGA, YATA, Fugue): represent the document as a mergeable data structure; work peer-to-peer without central ordering.
**Use when.** Real-time collaborative editing (Google Docs uses OT; newer systems like Yjs use CRDTs).
**Advantages.**
- OT: well-proven for text (Google Docs has used it for 15+ years); intent-preservation is strong
- CRDTs: no central server needed; work offline; simpler correctness reasoning
**Tradeoffs.**
- OT: transformation functions are notoriously hard to implement correctly for complex operations; server is a bottleneck
- CRDTs: metadata overhead (interleaving positions, tombstones); performance at scale
**Staff signal.** The industry trend is toward CRDTs (Yjs, Automerge) because they're easier to reason about formally and support offline-first. OT's correctness is fragile — subtle bugs in transformation functions are discovered years after deployment.

## Data Efficiency

### Compression Algorithms
**What.** Tradeoff between compression ratio and speed. zstd: excellent ratio with good speed (general purpose). lz4/snappy: fast with moderate compression (hot path, real-time). gzip/deflate: widely compatible, moderate speed and ratio.
**Use when.** Storage (cold data → zstd; hot data → lz4), network transfer (gzip for HTTP), message queues (snappy in Kafka).
**Advantages.**
- zstd: ~3-5× compression with ~500 MB/s decompression; dictionary mode for small payloads
- lz4: ~2× compression with ~4 GB/s decompression; near-zero CPU cost
**Tradeoffs.**
- Higher compression ratios cost more CPU (affects tail latency on hot paths)
- Dictionary-based codecs need the dictionary at decompression time
**Staff signal.** Choose based on access pattern: cold storage (S3 archives) favors ratio (zstd level 19); real-time data (message buses, caches) favors speed (lz4). Kafka uses snappy by default for this reason — the bandwidth saving is worth minimal CPU, but higher compression would add latency.

### Checksums and Error Detection
**What.** CRC32: fast hardware-accelerated error detection for data integrity (Ethernet, disk). xxHash: fast non-cryptographic hash for hash tables and checksumming. Cryptographic hashes (SHA-256): collision-resistant for content addressing and integrity verification.
**Use when.** CRC32 for transport/storage integrity. xxHash for performance-critical hashing. SHA-256 when adversarial tampering is a threat.
**Advantages.**
- CRC32/xxHash: nanosecond-scale computation; hardware support available
- End-to-end checksums detect corruption that layer-specific checks miss (silent disk corruption, memory bit flips)
**Tradeoffs.**
- CRC32 detects accidental errors but is not collision-resistant (attacker can craft collisions)
- Cryptographic hashes are ~100× slower than xxHash
**Staff signal.** The end-to-end argument: checksums at each layer (disk, network) don't guarantee end-to-end integrity because errors can occur between layers (in memory, during copy operations). Application-level checksums verified at the final consumer are the only way to guarantee integrity. This is why systems like ZFS and HDFS verify checksums on read.

### Erasure Coding vs Replication
**What.** Replication: store N full copies (3× storage for 3-replica). Erasure coding (Reed-Solomon): split data into k fragments, generate m parity fragments; any k of (k+m) fragments can reconstruct the data. E.g., 6+3 coding tolerates 3 failures with 1.5× storage overhead vs 3× for 3-replica.
**Use when.** Large-scale storage systems where replication's 200-300% overhead is too expensive (HDFS erasure coding, Google Colossus, Azure Storage).
**Advantages.**
- Dramatically reduces storage overhead while maintaining fault tolerance (1.5× vs 3×)
**Tradeoffs.**
- Reconstruction requires reading k fragments and computation (higher latency on degraded reads)
- Write amplification: each write produces k+m fragments that may go to different nodes
- Not suitable for hot data with frequent reads (latency cost of reassembly)
**Staff signal.** The tradeoff is storage cost vs read latency and reconstruction bandwidth. Use replication for hot, latency-sensitive data; use erasure coding for warm/cold data where storage cost dominates. HDFS introduced erasure coding specifically for cold data tiers.

## General Design Levers

### Probabilistic vs Exact Tradeoff
**What.** Many system design problems have exact solutions that are expensive (memory, latency, coordination) and approximate solutions that are cheap. The design decision is whether the use case tolerates approximation.
**Use when.** Counting (HLL vs exact distinct), membership (Bloom vs hash set), ranking (approximate top-K vs exact sort), percentiles (t-digest vs storing all values).
**Advantages.**
- Orders-of-magnitude resource savings for bounded error
**Tradeoffs.**
- Error bounds must be understood and acceptable for the use case
- Some use cases (financial, audit) require exactness
**Staff signal.** In interviews, mentioning "do we need exact, or is approximate acceptable here?" demonstrates design maturity. Many candidates jump to exact solutions that won't scale, when a 1% error bound would be invisible to users.

### Batching and Amortization
**What.** Grouping multiple operations into a single execution to amortize fixed costs (network round trip, disk seek, lock acquisition, system call overhead).
**Use when.** Any system where per-operation overhead dominates: database writes, network calls, log flushing, message publishing.
**Advantages.**
- Transforms per-item costs into per-batch costs; typical throughput improvement 10-100×
- Kafka achieves high throughput by batching messages into large sequential writes
**Tradeoffs.**
- Introduces latency (waiting to fill a batch); requires tuning batch size vs latency
- Batch failures are larger in scope (a failed batch affects all items in it)
**Staff signal.** Nagle's algorithm (TCP), Kafka producer batching, database WAL group commit, and GPU compute all exploit the same principle: amortize fixed cost across many items. The tunable is always: batch size / linger time vs acceptable latency.

### Backpressure-Aware Buffering / Ring Buffers
**What.** When a producer is faster than a consumer, the system must decide: drop data, buffer it (risking OOM), or signal the producer to slow down (backpressure). Ring buffers (fixed-size circular buffers) bound memory usage and make the overflow policy explicit (overwrite oldest or reject new).
**Use when.** Log pipelines, event streams, inter-thread communication, reactive systems.
**Advantages.**
- Ring buffers: fixed memory footprint; O(1) enqueue/dequeue; cache-friendly (LMAX Disruptor)
- Backpressure prevents cascading failures from unbounded queues
**Tradeoffs.**
- Backpressure propagates slowness upstream (may affect user experience)
- Ring buffer overflow means data loss unless overflow is signaled
**Staff signal.** Unbounded queues are a common source of production OOM failures. The LMAX Disruptor uses a ring buffer with sequence-based backpressure to achieve millions of operations/sec with predictable memory usage. In system design, always specify what happens when a buffer is full — this is where many designs fail under load.

## Common interview traps

- Using UUIDv4 as a primary key without acknowledging the B-tree index fragmentation cost — UUIDv7 or Snowflake solves this.
- Proposing consistent hashing without mentioning virtual nodes — raw consistent hashing gives terrible load distribution.
- Describing Bloom filters without noting they cannot delete (suggest counting or cuckoo filter if deletion is needed).
- Conflating HyperLogLog with exact counting — HLL gives ~1% error and cannot tell you which specific elements were seen.
- Proposing erasure coding for hot-path reads without acknowledging reconstruction latency.
- Averaging p99 latencies across servers as if the result is meaningful — use t-digest or histograms with proper merging.
- Choosing OT for collaborative editing without mentioning that it requires a central ordering server.
- Proposing CRDTs without mentioning the tombstone/metadata growth problem.
- Ignoring the cold start cost of compression dictionaries when recommending zstd for small messages.
- Using CRC32 where adversarial integrity is needed — CRC is not collision-resistant.

## Drill questions

1. You're designing a cache cluster that can grow from 10 to 100 nodes. How does consistent hashing minimize disruption, and what's the role of virtual nodes?
2. A database read path checks a Bloom filter before disk access. The filter has a 1% false positive rate. What's the actual overhead in terms of unnecessary disk reads per million queries?
3. You need global unique IDs for a database with 50K inserts/sec across 10 nodes. Compare UUIDv7 vs Snowflake IDs — which would you choose and why?
4. Two data centres each maintain a counter that users can increment. Describe a CRDT-based solution and explain the metadata cost.
5. Your monitoring system needs to report p99 latency globally from 500 servers. Why can't you average the per-server p99, and what do you use instead?
6. Design a system that finds the top-10 trending hashtags from 1M tweets/second with bounded memory. What data structures do you combine?
7. A storage system uses 3-way replication at 3× overhead. The team proposes erasure coding to reduce cost. What are the latency implications, and for what access pattern is this appropriate?
8. You're building autocomplete that searches over 100M terms. Compare a trie-based approach vs an inverted index approach. When would each win?
9. Explain why a ring buffer with explicit overflow policy is safer than an unbounded queue in a production log pipeline.
10. A collaborative editor uses CRDTs but document metadata grows over time. What causes this, and how do you mitigate it in production?
11. Your vector search returns 95% recall at 5ms. The product team wants 99% recall. What are your options and what will each cost?
12. How does the end-to-end argument apply to data integrity in a system where data flows through network → application → disk → replication?
