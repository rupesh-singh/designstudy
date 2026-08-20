# 3. Storage Engines, Indexing & Analytics

Storage engines are the machinery beneath your data model — they determine whether writes are fast or reads are fast, how much disk is consumed, and what operational burdens you inherit. This section covers the two dominant engine families (log-structured and page-oriented), the indexing strategies that make queries efficient, and the columnar storage techniques that power analytics at scale.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| LSM-tree (Log-Structured Merge) | Write-optimized engine using sorted runs | High write throughput is the priority |
| B-tree | Read-optimized balanced page tree | General OLTP with mixed read/write |
| Write / Read / Space amplification | Three-way tradeoff in storage engines | Evaluating engine suitability |
| Bloom filters | Probabilistic structure to skip absent keys | Reducing unnecessary disk reads in LSM |
| Compaction strategies | Merging sorted runs (size-tiered, leveled) | Tuning LSM-tree operational behavior |
| Primary vs Secondary index | Organizing access by main key vs alternate keys | Query optimization decisions |
| Covering / Composite index | Indexes that satisfy queries without heap lookup | Eliminating I/O for frequent queries |
| In-memory databases | Data kept entirely in RAM | Sub-millisecond latency requirements |
| OLTP vs OLAP | Transactional vs analytical workload shapes | Choosing engine and storage format |
| Column-oriented storage | Store values by column, not by row | Analytics scanning few columns over many rows |
| Star / Snowflake schema | Dimensional modeling for warehouses | Structuring analytical data |
| Materialized views | Pre-computed query results | Accelerating repeated expensive queries |

## Log-Structured Storage

### Append-Only Logs and Segment Compaction
**What.** The simplest storage engine: append every write to the end of a file. To avoid unbounded growth, the log is split into segments; closed segments are compacted (duplicate keys removed, keeping only the latest value) and merged. A hash index in memory maps each key to its byte offset in the current segment.
**Use when.** Understanding the foundation of all log-structured engines (Bitcask, Kafka log segments).
**Advantages.**
- Sequential writes are extremely fast (one disk seek or no seek on SSDs)
- Immutable segments simplify concurrency and crash recovery
**Tradeoffs.**
- Hash index must fit in memory; doesn't support range queries efficiently
- Compaction creates I/O spikes and temporarily doubles space usage
**Staff signal.** Kafka's log segments follow this exact pattern: append-only writes, segment compaction (log compaction mode), and retention policies. Understanding the base abstraction clarifies many distributed system internals.

### SSTables, Memtables & LSM-Trees
**What.** An SSTable (Sorted String Table) is a segment file where key-value pairs are sorted by key. A memtable is an in-memory balanced tree (red-black or skip list) that accumulates writes until it reaches a threshold, then flushes to disk as a new SSTable. The LSM-tree (Log-Structured Merge-tree) is the full system: writes go to memtable → flush to L0 SSTables → background compaction merges and sorts into deeper levels.
**Use when.** Any system requiring high write throughput: Cassandra, RocksDB (used inside CockroachDB, TiKV, MyRocks), LevelDB, HBase.
**Advantages.**
- Write throughput limited only by sequential I/O bandwidth
- Sorted structure enables efficient range queries
- Compression is very effective because compaction produces sorted, dense files
**Tradeoffs.**
- Reads may check multiple SSTables (memtable → L0 → L1 → ...) — read amplification
- Compaction consumes CPU and I/O in the background, can interfere with foreground traffic
- A crash between memtable write and flush loses data unless a WAL (write-ahead log) is maintained
**Staff signal.** The WAL is what makes LSM-trees durable: every write goes to an append-only WAL before the memtable. On crash recovery, replay the WAL to reconstruct the memtable. This is separate from the SSTables themselves.

### Compaction Strategies
**What.** *Size-tiered* (STCS): when enough similarly-sized SSTables accumulate, merge them into one larger one. Simpler, better write throughput, but creates large temporary space overhead and inconsistent read latency. *Leveled* (LCS): each level has a size limit; when exceeded, SSTables are merged into the next level. More predictable read latency and space usage, but higher write amplification. *Time-window* (TWCS): for time-series, SSTables are grouped by time window and never merged across windows; old windows are dropped whole.
**Use when.** Tuning a production LSM-tree system (Cassandra, RocksDB) for your specific workload.
**Advantages.**
- Size-tiered: lowest write amplification, best for write-heavy workloads
- Leveled: bounded space amplification (~10% overhead), predictable reads
- Time-window: efficient for TTL-based data, avoids compacting data that will be deleted soon
**Tradeoffs.**
- Size-tiered: up to 2× temporary space amplification during compaction; read amplification grows unboundedly
- Leveled: ~10–30× write amplification (each write may be rewritten through multiple levels)
- Time-window: doesn't help for non-time-partitioned workloads; out-of-order writes across windows cause tombstone issues
**Staff signal.** Write amplification is the hidden cost of leveled compaction — a single user write can result in 10–30 physical writes as data is promoted through levels. This matters for SSD lifetime (limited write endurance) and can be the bottleneck on write-heavy workloads.

### Write, Read, and Space Amplification
**What.** *Write amplification*: ratio of total bytes written to disk vs bytes written by the application (>1 because compaction rewrites data). *Read amplification*: number of disk reads needed to serve one logical read (>1 in LSM because multiple levels may be checked). *Space amplification*: ratio of actual disk used vs logical data size (>1 due to compaction overhead, obsolete entries not yet compacted). These three trade against each other — optimizing one worsens at least one other.
**Use when.** Evaluating or comparing storage engines for a specific workload.
**Advantages.**
- Framework for rigorous engine comparison (RocksDB team uses this triad extensively)
**Tradeoffs.**
- No engine wins on all three simultaneously; your workload determines which matters most
**Staff signal.** B-trees have lower read amplification (~O(log n) page reads) but higher space amplification (pages are typically 50-70% full due to splits). LSM-trees have lower space amplification (compaction produces dense files) but higher write amplification. Know this tradeoff cold.

### Bloom Filters in LSM Reads
**What.** A Bloom filter is a probabilistic data structure that can definitively say "this key is NOT in this SSTable" (no false negatives) or "this key MIGHT be in this SSTable" (possible false positives). Each SSTable has an associated Bloom filter. Before reading an SSTable from disk, check its Bloom filter — if negative, skip the disk I/O entirely.
**Use when.** Any LSM-tree point lookup. Cassandra, RocksDB, and HBase all use per-SSTable Bloom filters.
**Advantages.**
- Dramatically reduces read amplification for keys that don't exist (the common case in many workloads)
- Memory cost is small: ~10 bits per key gives ~1% false positive rate
**Tradeoffs.**
- Only helps point lookups, not range queries (can't bloom-filter a range)
- False positives cause unnecessary disk reads (small percentage, but nonzero)
- Memory for filters grows with total key count across all SSTables
**Staff signal.** Bloom filters don't help with range scans — this is why LSM-trees pay read amplification for range queries regardless of Bloom filter configuration. For range-heavy workloads, leveled compaction's bounded number of overlapping SSTables matters more.

## B-Trees

### B-Tree Structure and Operations
**What.** A self-balancing tree that stores data in fixed-size pages (typically 4-16KB). Internal pages contain keys and pointers to child pages; leaf pages contain keys and values (or pointers to heap rows). Lookups traverse O(log n) pages from root to leaf. Insertions may cause page splits when a page overflows. Updates modify pages in-place (unlike LSM append-only approach).
**Use when.** The default for nearly all relational databases (PostgreSQL, MySQL InnoDB, SQL Server) and most OLTP systems where read latency predictability matters.
**Advantages.**
- Predictable read latency: always exactly O(log_B n) page reads (B = branching factor, typically 100-500)
- In-place updates mean no background compaction overhead for reads
- Mature, well-understood, excellent tool support
**Tradeoffs.**
- In-place updates require a WAL (write-ahead log / redo log) for crash safety — every write goes to WAL then to the page
- Page splits create fragmentation over time (pages become partially full)
- Write throughput is lower than LSM because of random I/O for page updates
**Staff signal.** B-trees write each piece of data at least twice (WAL + page). LSM-trees also write multiple times (WAL + memtable flush + compaction), but LSM writes are sequential while B-tree page writes are random. On HDDs this difference is massive; on SSDs it's smaller but still significant.

### LSM vs B-Tree Comparison
**What.** The core tradeoff: LSM-trees optimize for write throughput (sequential I/O, batched compaction); B-trees optimize for read latency (predictable O(log n) lookups, no compaction interference). LSM-trees use less space (compaction produces dense files); B-trees fragment internally. LSM compaction can cause latency spikes; B-trees are more predictable but have lower peak write throughput.
**Use when.** Choosing a storage engine or explaining why a system made its choice.
**Advantages.**
- LSM: 5-10× higher write throughput on SSDs (RocksDB benchmarks), better compression
- B-tree: more predictable latency (no compaction pauses), better for read-heavy OLTP
**Tradeoffs.**
- LSM compaction at high write rates can starve foreground reads (compaction backlog)
- B-tree page splits cause occasional write latency spikes, but they're brief and local
**Staff signal.** The operational concern with LSM in production: if writes arrive faster than compaction can keep up, the number of L0 files grows unboundedly, read amplification explodes, and the system enters a death spiral. RocksDB has write stall mechanisms to prevent this, but they reduce write throughput (back-pressure). This is the LSM Achilles' heel.

### Fragmentation and Vacuum/Compaction Burden
**What.** B-trees fragment as pages split and rows are deleted/updated, leaving partially-full pages and dead space. PostgreSQL's MVCC leaves dead tuples that require VACUUM to reclaim. LSM-trees accumulate tombstones and obsolete entries that compaction must clean. Both require background maintenance operations that compete with foreground traffic.
**Use when.** Discussing operational concerns of any storage engine.
**Advantages.**
- Understanding maintenance burden prevents unexpected production degradation
**Tradeoffs.**
- PostgreSQL autovacuum can cause I/O storms on large tables; manual tuning often needed
- LSM compaction can spike latency by consuming I/O bandwidth
**Staff signal.** PostgreSQL's VACUUM is one of its most notorious operational challenges. Table bloat from failed autovacuum has caused outages at scale. In interviews, mentioning this shows real operational awareness beyond textbook knowledge.

## Index Types and Strategies

### Primary/Clustered vs Secondary/Non-Clustered Index
**What.** A *primary/clustered index* determines the physical storage order of rows (only one per table). In InnoDB, the primary key IS the clustered index; rows are stored in PK order. A *secondary index* is a separate structure pointing back to the primary key (InnoDB) or heap file location (PostgreSQL). Heap file storage means rows are stored in insertion order, with all indexes pointing to the row's physical location.
**Use when.** Choosing between index-organized tables (InnoDB) vs heap-based (PostgreSQL) storage, and understanding the cost of secondary indexes.
**Advantages.**
- Clustered index: range queries on the PK are extremely fast (physically sequential)
- Secondary indexes enable efficient queries on non-PK columns
**Tradeoffs.**
- Secondary indexes in InnoDB require two lookups: index → PK → clustered index (double lookup)
- Every secondary index adds write overhead (maintained on every insert/update/delete)
- Heap files avoid the double-lookup but scatter related rows across disk
**Staff signal.** In InnoDB, every secondary index leaf contains the primary key value, not a physical pointer. This means wide primary keys (like UUIDs) bloat every secondary index. This is why narrow, auto-incrementing PKs are preferred in InnoDB.

### Covering Indexes and Composite Indexes
**What.** A *composite (concatenated) index* indexes multiple columns in a specified order. Column order matters: an index on (A, B, C) efficiently serves queries filtering on A, (A, B), or (A, B, C), but NOT B alone or C alone (leftmost prefix rule). A *covering index* includes all columns a query needs, allowing the query to be served entirely from the index without touching the heap/table (index-only scan).
**Use when.** Optimizing hot queries to avoid table lookups.
**Advantages.**
- Covering index eliminates a random I/O per row for the covered query
- Composite indexes serve multiple query patterns with one structure
**Tradeoffs.**
- Wider indexes consume more memory and slow writes
- Column order is critical and serves one pattern well while potentially ignoring others
**Staff signal.** The "column order" insight is frequently tested: `WHERE a = ? AND b > ? ORDER BY c` benefits from index (a, b, c) only partially — the range predicate on b prevents using c for sort. Knowing how the optimizer uses composite indexes is a staff-level skill.

### Index Selectivity and Cardinality
**What.** *Cardinality*: the number of distinct values in a column. *Selectivity*: the fraction of rows a predicate eliminates. An index is most useful on high-cardinality columns (many distinct values → each lookup returns few rows). Indexing a boolean column (cardinality 2) rarely helps because the index lookup still returns ~50% of rows — a full scan may be cheaper.
**Use when.** Deciding which columns to index; explaining why the optimizer ignores an existing index.
**Advantages.**
- High-selectivity indexes reduce I/O dramatically (from table scan to few-page lookups)
**Tradeoffs.**
- Low-selectivity indexes waste space and slow writes without helping reads
- The optimizer's cost model may choose a sequential scan over an index scan when selectivity is poor
**Staff signal.** An index on a column with 3 distinct values across 100M rows is nearly useless for point lookups. But combined in a composite index (low-cardinality column first, then high-cardinality), it can still be useful for partitioning within the composite structure.

### Multi-Dimensional and Spatial Indexes (R-trees)
**What.** Standard B-tree indexes work on a single ordering dimension. Multi-dimensional indexes (R-trees, kd-trees, space-filling curves like Z-order/Hilbert) allow efficient queries on multiple dimensions simultaneously: geo-spatial (latitude + longitude), or multi-attribute range queries.
**Use when.** "Find all restaurants within 5km" or "find products with price 10-50 AND rating > 4."
**Advantages.**
- Enables queries that would otherwise require scanning one dimension then filtering the other
- PostGIS uses R-trees (via GiST) for spatial indexing in PostgreSQL
**Tradeoffs.**
- More complex to maintain than B-trees; splits are harder to optimize
- Less effective in very high dimensions (curse of dimensionality)
**Staff signal.** A common interview approach for geo-queries is geohashing (Z-order curve), which reduces 2D to 1D so a standard B-tree can be used. This loses some efficiency at boundaries but works with any database that supports range queries.

### Full-Text Search and Inverted Indexes
**What.** An inverted index maps each term (word/token) to the list of documents containing it. This enables full-text search — "find all documents containing 'distributed' AND 'consensus'." Systems: Elasticsearch (Lucene-based), PostgreSQL's GIN indexes, Apache Solr.
**Use when.** Text search, log search, or any query based on content words rather than exact field matches.
**Advantages.**
- Sub-second search across billions of documents
- Supports fuzzy matching (edit distance), stemming, synonyms, ranking (TF-IDF, BM25)
**Tradeoffs.**
- Significant storage overhead (the inverted index can be as large as the source data)
- Write latency for index updates; often uses near-real-time refresh rather than immediate
**Staff signal.** Elasticsearch's near-real-time search (default 1-second refresh) means recently written documents aren't immediately searchable. For truly real-time requirements, this matters and may require forcing a refresh (at throughput cost).

## In-Memory and Durability

### In-Memory Databases
**What.** Databases that keep the entire dataset in RAM (Redis, Memcached, VoltDB, MemSQL/SingleStore). Their speed advantage comes not primarily from avoiding disk reads (OS page cache achieves that for hot data in disk-based DBs) but from avoiding the overhead of encoding data in disk-friendly formats and managing disk-oriented data structures.
**Use when.** Sub-millisecond latency requirements, caching layers, or datasets that fit in memory.
**Advantages.**
- 10-100× lower latency than disk-based engines for the same operations
- Can implement data structures (priority queues, sets, sorted sets) that are awkward on disk
**Tradeoffs.**
- Data loss on crash unless persistence is configured (Redis AOF/RDB, VoltDB command log)
- Cost per GB is ~50× higher than SSD storage
- Dataset must fit in available RAM (or use tiered approaches)
**Staff signal.** The real speed advantage of in-memory DBs is eliminating serialization/deserialization overhead and pointer-based data structures that would be inefficient on disk. Even with OS page cache warming a disk-based DB, the in-memory DB wins because it skips the disk-format encoding layer entirely.

### Durability Mechanisms
**What.** *WAL (Write-Ahead Log)*: every modification is logged to an append-only file before applying to data structures; on crash, replay the log. *fsync*: forces OS to flush buffered writes to physical media (expensive; ~1-10ms per call). *Group commit*: batch multiple transactions' WAL entries into a single fsync to amortize the cost. *Replication as durability*: rather than fsync to local disk, replicate to N nodes — if any one survives, data is safe.
**Use when.** Designing or evaluating any system's durability guarantees.
**Advantages.**
- WAL + fsync provides crash-consistent durability on a single node
- Group commit turns per-transaction fsync cost into per-batch cost (10-100× throughput improvement)
- Replication-based durability can be faster than fsync (network round trip < forced disk flush in some configurations)
**Tradeoffs.**
- fsync on every commit limits throughput to ~100-1000 TPS per disk (without group commit)
- Replication-based durability without fsync risks data loss if all replicas fail simultaneously (correlated failure)
**Staff signal.** Some systems (like Redis with default config, or Kafka with acks=1) sacrifice durability for throughput. In interviews, always ask: "what's the durability guarantee here?" and know the mechanisms that back it up.

## OLTP vs OLAP and Warehousing

### OLTP vs OLAP Workload Characteristics
**What.** OLTP (Online Transaction Processing): short queries, random access by key, read/write mix, high concurrency, row-at-a-time operations (e-commerce, banking). OLAP (Online Analytical Processing): long-running scans over many rows, read-heavy, few concurrent queries, column-at-a-time aggregations (business intelligence, reporting).
**Use when.** Choosing storage engine, schema design, and indexing strategies.
**Advantages.**
- Recognizing the workload type immediately narrows technology choices
**Tradeoffs.**
- Running OLAP queries on an OLTP database degrades transaction performance
- Maintaining a separate analytical store (warehouse) adds ETL complexity and staleness
**Staff signal.** The separation exists because the optimal physical data layout for each workload is fundamentally different: row-oriented for OLTP (access whole rows), column-oriented for OLAP (scan specific columns across millions of rows).

### Data Warehousing, Star Schema & Snowflake Schema
**What.** A data warehouse receives data via ETL (Extract, Transform, Load) or ELT (load raw, then transform in-warehouse) from OLTP systems. Dimensional modeling uses a *star schema*: a central fact table (events/transactions with metrics and foreign keys) surrounded by dimension tables (descriptive attributes — who, what, where, when). A *snowflake schema* further normalizes dimensions into sub-dimensions.
**Use when.** Designing analytical data infrastructure.
**Advantages.**
- Star schema is optimized for aggregation queries: "total revenue by product category by region by month"
- Dimension tables are small (fit in memory), fact tables are huge but narrow per-query (few columns scanned)
**Tradeoffs.**
- ETL pipeline maintenance is a significant ongoing cost
- Star schema denormalizes dimensions (duplicates descriptive data across time), complicating historical accuracy
**Staff signal.** Fact tables commonly have billions of rows but queries typically scan only 4-5 columns. This is exactly why column-oriented storage wins for analytics — you read only the columns you need, ignoring the other hundreds.

## Column-Oriented Storage and Analytics

### Column-Oriented Storage
**What.** Instead of storing all columns of a row together (row-oriented), store all values of a single column together. A query scanning revenue across 1 billion rows reads only the revenue column file, not the 200 other columns. Systems: Parquet (file format), Redshift, BigQuery, ClickHouse, DuckDB.
**Use when.** Analytical queries that aggregate a few columns over many rows.
**Advantages.**
- 10-100× less I/O for typical analytical queries (only read needed columns)
- Excellent compression: values in a column tend to be similar (same data type, often repeating values)
- Enables vectorized processing (operate on column vectors, not row-by-row)
**Tradeoffs.**
- Point queries (fetch one row by ID) are expensive — must read a position from each column file
- Writes are complex (must update many column files atomically); often uses batch/micro-batch ingestion
**Staff signal.** Column-oriented storage isn't just about I/O reduction — it also enables CPU-cache-efficient vectorized processing because operations on a single column vector (all same type, sequential in memory) play perfectly with CPU prefetching and SIMD instructions.

### Column Compression Techniques
**What.** *Bitmap encoding*: for low-cardinality columns, represent each distinct value as a bit vector (1 bit per row). *Run-length encoding (RLE)*: when sorted, consecutive identical values compress to (value, count) pairs. *Dictionary encoding*: replace repeated string values with integer codes, store the dictionary separately. These compose: dictionary-encode, then bitmap or RLE on the codes.
**Use when.** Understanding why columnar stores achieve 5-20× compression over row-oriented storage.
**Advantages.**
- Bitmap indexes enable bitwise AND/OR operations for multi-predicate queries (extremely fast)
- RLE on sorted columns can compress billions of rows into megabytes
- Dictionary encoding turns string comparisons into integer comparisons
**Tradeoffs.**
- High-cardinality columns (UUIDs, timestamps) compress poorly with bitmaps
- Sort order choice affects which columns compress well (only the first sort column gets maximum RLE benefit)
**Staff signal.** Vertica and ClickHouse allow multiple sort orders (projections/materialized views with different orderings) so different query patterns each get optimal compression and scan performance. The tradeoff is storage multiplication.

### Vectorized Processing and CPU Cache Efficiency
**What.** Rather than processing one row at a time (Volcano/iterator model), vectorized engines process batches of column values (typically 1000-4096 values) as tight loops over arrays. This exploits CPU caches (sequential memory access), branch prediction (same operation repeatedly), and SIMD instructions (parallel arithmetic on 4-8 values per instruction).
**Use when.** Understanding why modern analytical engines (DuckDB, ClickHouse, DataFusion) are orders of magnitude faster than row-at-a-time processing.
**Advantages.**
- 10-50× speedup over row-at-a-time interpretation for scan-heavy queries
- Better utilization of modern CPU capabilities (out-of-order execution, prefetch)
**Tradeoffs.**
- More complex engine implementation; harder to support UDFs (user-defined functions) efficiently
- Benefits diminish for queries dominated by random access or complex joins
**Staff signal.** The combination of columnar format + compression + vectorized execution is why BigQuery can scan petabytes in seconds — each layer multiplies the efficiency: less I/O (columnar), less data to decompress (compression), faster processing of what remains (vectorized).

### Sort Order in Column Stores
**What.** Even though data is stored by column, the row order within columns is consistent (row N in column A corresponds to row N in column B). Choosing a sort order (e.g., sort by date, then by customer_id) improves compression of early sort columns (long runs of identical values) and accelerates queries filtering on those columns. Multiple sort orders can be stored as separate copies.
**Use when.** Physical design of a columnar table or choosing sort keys in Redshift/BigQuery.
**Advantages.**
- First sort key gets maximum compression benefit (RLE)
- Queries filtering on sort key columns skip large segments via min/max metadata
**Tradeoffs.**
- Only one physical sort order per copy; other access patterns don't benefit
- Multiple sort orders multiply storage cost
**Staff signal.** Redshift's SORTKEY and BigQuery's clustering columns serve this purpose. Choosing the right sort key requires knowing your dominant query patterns — sort by the highest-cardinality filter first for maximum pruning.

### Materialized Views and Data Cubes
**What.** A *materialized view* is a pre-computed query result stored on disk. Unlike a regular view (re-executed on each query), a materialized view trades storage and write-time computation for read-time speed. A *data cube* (OLAP cube) is a special case: pre-aggregated facts along all combinations of dimensions (e.g., total sales by product × region × month).
**Use when.** Accelerating frequently-executed expensive queries, especially aggregations.
**Advantages.**
- Turns expensive analytical queries into simple lookups
- Data cubes answer dimensional rollup/drill-down queries instantly
**Tradeoffs.**
- Maintenance cost: every write to base data must update all affected materialized views (write amplification)
- Storage overhead for materialized results
- Freshness lag if views are refreshed periodically rather than synchronously
- Data cubes lose flexibility: only pre-aggregated dimensions are fast; ad-hoc queries still hit raw data
**Staff signal.** Materialized views represent a space-time tradeoff analogous to caching, but at the query level. The interview-worthy insight is that most columnar engines are fast enough that raw scans beat pre-materialized cubes for ad-hoc exploration — cubes mainly help for dashboards with known, fixed queries.

## Common interview traps

- Saying LSM-trees are "better" without qualifying: they're better for write throughput but worse for read latency predictability and can suffer compaction stalls.
- Claiming in-memory databases are fast "because they avoid disk" — the real advantage is avoiding disk-format serialization overhead; disk-based DBs with warm caches also avoid disk reads.
- Confusing clustered index with primary key — they're the same in InnoDB but different in PostgreSQL (which uses heap files).
- Forgetting that composite index column order matters: index (A, B) does NOT serve a query filtering only on B.
- Assuming Bloom filters help range queries — they only help point lookups.
- Using "column-oriented" and "wide-column" interchangeably — Cassandra is wide-column (row-key oriented); Parquet is column-oriented (stores each column separately).
- Ignoring write amplification when recommending leveled compaction for a write-heavy workload.
- Forgetting that materialized views must be maintained on writes — they're not free reads.

## Drill questions

1. Your system ingests 500K events/second and needs to serve both real-time point lookups by event ID and analytical aggregations over time ranges. How would you design the storage layer?
2. Explain why an LSM-tree can enter a "compaction death spiral." What operational controls prevent it?
3. A PostgreSQL table with 100M rows has a secondary index on `status` (3 distinct values). A query `WHERE status = 'active'` is slow. Why might the optimizer choose a sequential scan over the index? Is the index useful at all?
4. Compare the write path of InnoDB (B-tree) and RocksDB (LSM). How many times is a single logical write physically written in each?
5. You're designing a time-series metrics system (10M unique series, 1 point/second each). Would you choose size-tiered or time-window compaction? Why?
6. Why does sorting a column-store by one column improve compression? What happens to compression of other columns?
7. When would you choose a covering index over simply adding a column to an existing composite index?
8. A data warehouse query scans 1TB of fact table data but only needs 3 of 200 columns. Estimate the I/O reduction from column-oriented vs row-oriented storage.
9. Your Redis instance uses 50GB of RAM for a cache. The boss asks "why not just use PostgreSQL with warm page cache?" What's your answer?
10. Explain group commit. Why does increasing batch size improve throughput but hurt latency? Where's the sweet spot?
