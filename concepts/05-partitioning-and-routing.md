# 5. Partitioning, Sharding & Request Routing

Partitioning (also called sharding) splits a large dataset across multiple machines so that no single node bears the full storage or query load. It composes with replication — each partition is typically replicated for fault tolerance. The core challenges are choosing a partition key that distributes load evenly, handling hot spots, maintaining secondary indexes, rebalancing without downtime, and routing requests to the correct partition.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Key-range partitioning | Splits data by sorted key intervals | You need efficient range scans |
| Hash partitioning | Splits data by hash of key | You need uniform distribution and don't need range queries |
| Consistent hashing | Distributes keys on a ring with minimal reshuffling on resize | Adding/removing nodes should move minimal data |
| Rendezvous hashing | Each key independently picks its highest-scoring node | Simpler alternative to consistent hashing with good distribution |
| Jump consistent hash | O(1) memory, near-perfect balance | Fixed node set with no heterogeneous weighting needed |
| Hot-key salting | Appends random suffix to spread hot keys | Celebrity/viral-key problem overwhelms one partition |
| Compound primary key | Partition key + sort key | Range queries within a partition boundary |
| Local secondary index | Each partition indexes its own data | Write-efficient; accept scatter-gather on reads |
| Global secondary index | Index is itself partitioned by term | Read-efficient; accept async distributed writes |
| Fixed partition count | Pre-allocate many partitions, assign to nodes | Simple rebalancing by moving whole partitions |
| Dynamic partitioning | Split/merge partitions based on size | Adapts to unknown or evolving data distribution |
| Proportional to nodes | Fixed partitions per node; split on node add | Good balance with uniform hash distribution |
| Request routing | Directing a query to the correct partition | Every partitioned system needs a routing strategy |
| Gossip protocol | Decentralized membership and partition map propagation | Avoiding single point of failure in routing |
| Resharding | Moving data between partitions operationally | Growing beyond initial partition scheme |
| Functional partitioning | Different features on different databases | Isolating workloads by function |
| Vertical partitioning | Splitting columns across stores | Wide rows with different access patterns |
| Federation | Splitting by function into separate databases | Independent scaling per domain |

## Partitioning Fundamentals

### Partitioning vs Replication — How They Compose

**What.** Partitioning divides data so each record lives on a subset of nodes; replication copies each partition to multiple nodes for fault tolerance. They are orthogonal: a system with 10 partitions and replication factor 3 has each partition on 3 nodes, totaling 30 partition-replicas across the cluster.

**Use when.** Any dataset too large for one node (partitioning) that also needs fault tolerance (replication).

**Advantages.**
- Combining both gives horizontal scaling for throughput AND survival of node failures
- Each partition can have its own leader and followers, distributing both write and read load

**Tradeoffs.**
- Operational complexity multiplies: partition rebalancing interacts with replica rebalancing
- Cross-partition operations (joins, transactions) must coordinate across multiple replication groups

**Staff signal.** Always draw the two dimensions independently in a design discussion — a common error is treating "3 replicas" as if it gives you 3× throughput (it gives availability, not partitioning).

### Key-Range Partitioning

**What.** Data is divided into contiguous ranges of the sort key (e.g., A-G on node 1, H-N on node 2, etc.). Each partition owns a contiguous slice of the key space. Used by HBase, early Bigtable, and MongoDB (when using ranged sharding).

**Use when.** Your primary access pattern is range scans (time-series data, alphabetical lookups, sequential keys).

**Advantages.**
- Range queries are efficient — a single partition serves an entire range without scatter-gather
- Data locality for adjacent keys enables efficient batch processing

**Tradeoffs.**
- Prone to hot spots if access is skewed toward one key range (e.g., today's date in a time-series)
- Partition boundaries need manual or automatic adjustment as data distribution shifts

**Staff signal.** Time-series data with key-range partitioning by timestamp concentrates all writes on the "current" partition — the fix is to prefix with a different dimension (sensor ID, region) so writes fan out.

### Hash Partitioning

**What.** A hash function is applied to the key, and the hash space is divided among partitions. Cassandra, DynamoDB, and MongoDB (hashed shard key) all use this.

**Use when.** You want uniform distribution regardless of key ordering and your primary access pattern is point lookups.

**Advantages.**
- Distributes even pathologically ordered keys (sequential IDs, timestamps) uniformly
- Eliminates hot spots from natural key ordering

**Tradeoffs.**
- Range queries become scatter-gather operations — you lose key adjacency
- The hash function is a one-way transformation; you cannot reconstruct key ordering from hash order

**Staff signal.** Cassandra's compromise is the compound primary key: the first component is hashed for partition assignment, the remaining components are stored sorted within that partition — enabling range queries within a partition.

### Consistent Hashing and Virtual Nodes

**What.** Keys and nodes are both mapped onto a ring (hash space). Each key is assigned to the nearest node clockwise on the ring. Virtual nodes (vnodes) place each physical node at multiple ring positions for better balance.

**Use when.** You need to add or remove nodes with minimal data movement (only keys between the new/removed node and its neighbor move).

**Advantages.**
- On node addition, only ~1/N of keys move (with vnodes, even more uniform)
- No centralized assignment table needed — the ring position is computable

**Tradeoffs.**
- Without sufficient vnodes, distribution can be highly uneven (especially with few nodes)
- Vnodes complicate range queries (a node's data is no longer contiguous in key space)
- Naive modulo hashing (key % N) moves almost all keys on resize — consistent hashing exists to avoid this

**Staff signal.** "Consistent hashing" in practice (Cassandra, DynamoDB) rarely uses the original Karger et al. algorithm directly — they use the concept (minimize movement on resize) but implement it with explicit token ranges or virtual nodes.

### Rendezvous Hashing and Jump Consistent Hash

**What.** Rendezvous (highest random weight): for each key, compute a score for every node, assign to the highest-scoring node. Jump consistent hash: an O(1)-memory algorithm producing near-perfect balance for a numbered set of buckets.

**Use when.** Rendezvous: when you want minimal key movement on node changes with simple implementation (used in some CDN routing). Jump: when the node set is numbered 0..N-1 and heterogeneous weighting isn't needed.

**Advantages.**
- Rendezvous: moving only keys that mapped to a removed node; no ring or vnode complexity
- Jump: O(ln N) computation, O(1) memory, mathematically perfect balance

**Tradeoffs.**
- Rendezvous: O(N) computation per key (must score all nodes); impractical for large N
- Jump: doesn't support weighted nodes or non-sequential node IDs; removing a non-last node is expensive

**Staff signal.** Jump consistent hash is theoretically optimal for balance but only practical when nodes are a contiguous numbered set — real systems with dynamic membership usually stick with consistent hashing + vnodes.

## Hot Spots and Compound Keys

### Skew, Hot Spots, and Key Salting

**What.** Even with hash partitioning, a single extremely popular key (a celebrity's user ID, a viral post ID) concentrates all traffic on one partition — a hot spot. Key salting appends a random number (e.g., key_01 through key_99) to split the hot key across multiple partitions.

**Use when.** You've identified specific keys that receive disproportionate traffic (measurable through partition-level metrics).

**Advantages.**
- Spreads a single hot key across N partitions (where N is the number of salt values)

**Tradeoffs.**
- Reads must now scatter-gather across all salt values and merge results
- Application must maintain metadata about which keys are salted (salting everything is wasteful)
- Increases read latency and complexity proportional to the salt cardinality

**Staff signal.** Key salting is a reactive, per-key optimization — it's not a partitioning strategy. You need monitoring to detect hot keys and apply salting selectively. Instagram/Twitter handle celebrity accounts this way.

### Compound Primary Keys

**What.** A compound key uses the first component for partition assignment (hashed or range-based) and subsequent components as a sort/clustering key within that partition. Cassandra's PRIMARY KEY ((partition_key), clustering_col1, clustering_col2) is the canonical example.

**Use when.** You need efficient range queries within a partition but uniform distribution across partitions (e.g., all messages for a conversation sorted by timestamp).

**Advantages.**
- Single-partition range scans (no scatter-gather) for queries within the clustering key
- Partition key provides distribution; sort key provides query efficiency

**Tradeoffs.**
- All data for a partition key must fit on one node (partition size limit)
- Query patterns are locked to the partition key — querying by clustering key alone requires a secondary index or a different table

**Staff signal.** The compound key design forces you to model data around query patterns (not entities) — this is why Cassandra data modeling is "query-first" rather than "entity-first."

## Secondary Indexes in Partitioned Systems

### Local (Document-Partitioned) Secondary Index

**What.** Each partition maintains its own secondary index covering only the data in that partition. A query on the secondary index must be sent to all partitions (scatter-gather) because no single partition knows which contains matching records.

**Use when.** Write performance is the priority — updating the secondary index is local, touching only one partition.

**Advantages.**
- Writes are fast — index update is co-located with the data
- No distributed coordination for index maintenance

**Tradeoffs.**
- Reads on secondary index are expensive — O(partitions) queries, merged by the coordinator
- Tail latency amplified by the slowest partition in the scatter-gather

**Staff signal.** MongoDB, Cassandra, and Elasticsearch (per-shard indexes) all use local secondary indexes — the read cost is why they push you toward query-first data modeling to avoid secondary index lookups.

### Global (Term-Partitioned) Secondary Index

**What.** The secondary index is itself partitioned (usually by the indexed term). A lookup on the index hits one or few partitions, but a write to the base data may need to update index entries on multiple remote partitions.

**Use when.** Read performance on secondary indexes is critical and write amplification is acceptable.

**Advantages.**
- Reads are efficient — only the partition(s) owning the relevant index term are queried
- No scatter-gather for point lookups on the index

**Tradeoffs.**
- Writes are distributed — a single document write may update multiple index partitions
- Index updates are typically asynchronous (eventually consistent) to avoid distributed transactions on every write
- DynamoDB GSIs exhibit this: they're eventually consistent by default

**Staff signal.** The read/write tradeoff is the core interview answer: local indexes favor writes (local update) at the cost of reads (scatter-gather); global indexes favor reads (point lookup) at the cost of writes (distributed update).

## Rebalancing Strategies

### Fixed Number of Partitions

**What.** Create many more partitions than nodes at startup (e.g., 1000 partitions across 10 nodes). When nodes are added/removed, whole partitions move between nodes — partition boundaries never change. Used by Riak, Elasticsearch, and early Cassandra.

**Advantages.**
- Rebalancing is simple: move whole partitions, no splitting or merging
- Operationally predictable — partition count is constant

**Tradeoffs.**
- Must choose partition count at creation time — too few means partitions become too large; too many means excessive metadata overhead
- Cannot adapt if data distribution changes dramatically after initial setup

**Staff signal.** The partition count must be "just right" for the dataset's eventual size — choosing it at creation time requires forecasting, which is often wrong.

### Dynamic Partitioning

**What.** Partitions split when they exceed a size threshold and merge when they shrink below another threshold. Used by HBase and MongoDB (auto-split).

**Advantages.**
- Adapts to actual data distribution — no upfront sizing decisions
- Works well when distribution is unknown or shifts over time

**Tradeoffs.**
- Splitting/merging causes transient load spikes and replication traffic
- A single initial partition creates a bottleneck until the first split (pre-splitting helps)

**Staff signal.** The operational risk is cascading splits under write bursts — a sudden data ingest can trigger many splits simultaneously, overwhelming the cluster. Pre-splitting mitigates this.

### Partitioning Proportional to Nodes

**What.** Each node owns a fixed number of partitions. When a new node joins, it splits some existing partitions and takes ownership of half. Cassandra (with vnodes) uses this approach.

**Advantages.**
- Partition count grows naturally with cluster size
- Balance is maintained automatically as the cluster scales

**Tradeoffs.**
- Splitting is randomized (hash-based), which can produce temporarily uneven splits
- Requires stable hashing to avoid cascading reassignments

**Staff signal.** This approach works well with hash partitioning but poorly with range partitioning because random splits don't respect key-range semantics.

### Why Hash-Mod-N Rebalancing Is Bad

**What.** If you assign partitions as `hash(key) mod N` where N is the node count, changing N causes almost all keys to remap to different nodes.

**Use when.** Never in production — this is the anti-pattern that consistent hashing exists to avoid.

**Tradeoffs.**
- Adding one node causes ~(N-1)/N of all data to move — nearly 100% data migration
- During migration, the system has split ownership, causing reads to check old and new locations

**Staff signal.** The key insight is that `mod N` creates a dependency between key assignment and cluster size — consistent hashing breaks this dependency.

## Request Routing and Service Discovery

### Routing Approaches

**What.** Three patterns: (1) A dedicated routing tier (proxy) that knows the partition map and forwards requests. (2) Any-node forwarding — any node accepts the request and forwards internally to the correct partition owner. (3) Partition-aware client — the client itself knows the partition map and connects directly to the right node.

**Use when.** Every partitioned system must solve routing; the choice depends on operational constraints and performance requirements.

**Advantages.**
- Routing tier: simple clients, centralized logic, easy to update
- Any-node: no separate infrastructure, clients just connect to any node
- Partition-aware client: lowest latency (no extra hop), but client complexity increases

**Tradeoffs.**
- Routing tier: additional latency hop, single point of failure (must be replicated)
- Any-node: internal forwarding adds latency for misrouted requests
- Partition-aware client: clients must subscribe to partition map changes; stale maps cause misroutes

**Staff signal.** ZooKeeper/etcd often stores the authoritative partition map, and participants (proxy, nodes, or clients) subscribe to changes. Kafka uses ZooKeeper for this; Cassandra uses gossip to propagate the token ring to all nodes and clients.

### Gossip Protocols for Membership

**What.** Each node periodically exchanges membership and partition-map information with random peers. Changes propagate epidemically through the cluster. Cassandra and Riak use gossip to disseminate the token ring.

**Use when.** You want decentralized service discovery without a coordination service as a single point of failure.

**Advantages.**
- No SPOF — any node can answer "who owns this key?"
- Convergence is fast (O(log N) rounds for N nodes)

**Tradeoffs.**
- Eventual convergence — during propagation, different nodes may have inconsistent views
- Debugging is harder — there's no single authoritative source to inspect

**Staff signal.** Gossip trades consistency of the metadata (partition map) for availability of the metadata service — the tradeoff mirrors the data plane's own CAP tradeoff.

## Operational Concerns

### Resharding Operationally

**What.** When you outgrow your partition scheme and must re-partition (change partition count, change partition key), the operational playbook is: dual-write to old and new partition schemes, backfill historical data into new partitions, verify consistency, then cut over reads.

**Use when.** The original partition key no longer distributes evenly, or you're migrating between storage systems.

**Advantages.**
- Dual-write + backfill enables zero-downtime migration
- Verification step catches data discrepancies before cutover

**Tradeoffs.**
- Dual-write period doubles write load and introduces consistency risks (what if one write fails?)
- Backfill can take days/weeks for large datasets; must handle concurrent writes during backfill
- Rollback requires maintaining the old scheme throughout

**Staff signal.** The dual-write phase is where bugs hide — prefer CDC-based replication from old to new (capturing the change stream) over application-level dual-write, which is prone to inconsistency if one write fails.

### Multi-Tenancy and Noisy Neighbours

**What.** In multi-tenant systems, partitioning by tenant isolates workloads. A "noisy neighbour" is a tenant whose traffic overwhelms a shared partition, degrading performance for co-located tenants.

**Use when.** SaaS platforms where tenants have vastly different usage patterns (one enterprise tenant may outweigh thousands of free-tier tenants).

**Advantages.**
- Tenant-based partitioning enables per-tenant scaling, throttling, and isolation
- Large tenants can be assigned dedicated partitions/nodes

**Tradeoffs.**
- Small tenants sharing partitions still risk noisy-neighbour effects
- Over-isolation wastes resources (one node per tiny tenant is expensive)

**Staff signal.** The practical solution is tiered isolation: small tenants share partitions with rate limiting; large tenants get dedicated partitions; the largest get dedicated clusters. The boundary is defined by SLA, not just size.

### Functional vs Horizontal vs Vertical Partitioning

**What.** Functional partitioning: different features/domains use entirely separate databases (users DB, orders DB, inventory DB). Horizontal partitioning (sharding): same table split by rows across nodes. Vertical partitioning: same table split by columns (wide table → frequently accessed columns vs. rarely accessed columns on different stores).

**Use when.** Functional when domains are independent and benefit from separate scaling. Horizontal when a single table is too large. Vertical when columns have divergent access patterns (e.g., blob data vs. metadata).

**Advantages.**
- Functional: independent deployment, scaling, and failure isolation per domain
- Horizontal: linear scaling for row count and throughput
- Vertical: optimizes I/O by separating hot columns from cold columns

**Tradeoffs.**
- Functional: cross-domain queries require application-level joins or data pipelines
- Horizontal: cross-shard queries (joins, aggregations) are expensive
- Vertical: reassembling the full row requires joining across stores

**Staff signal.** Federation (functional partitioning) is often the first step in scaling a monolithic database — split by bounded context before you shard individual tables.

### Parallel Query Execution (MPP)

**What.** Massively parallel processing engines (Redshift, BigQuery, Presto, Snowflake) split complex analytical queries across all partitions for parallel execution, then combine results.

**Use when.** Analytical workloads with full-table scans, aggregations, and joins that benefit from partition-level parallelism.

**Advantages.**
- Query latency scales inversely with partition count for scan-heavy workloads
- Leverages all cluster resources for a single query

**Tradeoffs.**
- Shuffle/exchange between partitions for joins is network-intensive
- Stragglers (one slow partition) dominate query latency

**Staff signal.** MPP systems trade per-query resource isolation for throughput — a single large query can consume the entire cluster's resources, which is why they use workload management/queuing.

## Common interview traps

- Forgetting that partitioning and replication are orthogonal and compose — each partition is independently replicated.
- Using hash-mod-N and not realizing that adding one node moves nearly all data.
- Assuming hash partitioning preserves range-query efficiency — it destroys it entirely.
- Conflating consistent hashing (the concept) with the specific Karger ring algorithm — real systems use token ranges.
- Not distinguishing local vs global secondary indexes when asked "how do secondary indexes work in a sharded system."
- Assuming rebalancing is instantaneous — large partition moves take time and consume bandwidth.
- Proposing to "shard by user ID" without considering that some users are 1000× more active than others (celebrity problem).
- Treating functional partitioning (federation) and horizontal partitioning (sharding) as the same thing.

## Drill questions

1. You have a social media system where 0.01% of users generate 50% of write traffic. How do you partition to avoid hot spots while maintaining query efficiency?
2. Walk through what happens physically when you add a 4th node to a 3-node cluster using consistent hashing with 256 vnodes per node.
3. Your system uses local secondary indexes. A query on a secondary attribute touches all 100 partitions. How do you reduce tail latency?
4. Why would you choose a fixed partition count (1000 partitions) over dynamic partitioning? Under what conditions does this choice backfire?
5. Explain the read/write tradeoff between local and global secondary indexes. Which would you choose for a system with 95% reads?
6. You're migrating from 8 shards to 32 shards with zero downtime. Describe the operational steps and where failures can occur.
7. A multi-tenant SaaS system partitions by tenant ID. One tenant grows to 100× the size of others. What are your options without changing the partition key?
8. When would you prefer rendezvous hashing over consistent hashing? What constraint makes consistent hashing the better choice?
9. Explain how Cassandra's compound primary key gives you both uniform distribution and within-partition range scans.
10. A partition-aware client has a stale partition map. What happens to the request, and how is this resolved?
