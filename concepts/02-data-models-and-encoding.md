# 2. Data Models, Query Languages & Encoding

Choosing a data model is one of the most consequential architectural decisions because it shapes how you think about the problem, what queries are natural, and how the system evolves. This section covers the major model families (relational, document, graph, wide-column, key-value, time-series), the encoding formats that move data between systems, and the compatibility concerns that arise during rolling upgrades.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---------|--------------|-------------------|
| Relational model | Tables with fixed schemas, joins, and strong consistency | Most OLTP with complex relationships |
| Normalization / Denormalization | Eliminating vs reintroducing redundancy | Balancing write consistency vs read performance |
| Document model | Nested, self-contained records | Data has natural hierarchy, accessed whole |
| Graph model | Nodes and edges with flexible traversal | Highly connected data, variable-depth relationships |
| Wide-column model | Sparse, row-key partitioned column families | High write throughput with known access patterns |
| Key-value model | Simple opaque lookup by key | Caching, session storage, high-throughput simple gets/puts |
| Time-series model | Append-heavy, timestamp-indexed data | Metrics, IoT, event streams |
| Schema-on-read vs schema-on-write | Flexibility vs safety of structure enforcement | Choosing between document and relational |
| Encoding formats (Protobuf, Avro, Thrift) | Compact, schema-evolving binary serialization | Cross-service communication, long-term storage |
| Schema evolution & compatibility | Safely changing schemas without breaking readers/writers | Rolling upgrades, multi-version deployments |
| Dataflow modes | Patterns for data movement between components | Choosing REST vs async messaging vs shared DB |
| Data lake / warehouse / lakehouse | Analytical storage paradigms | Choosing where analytical data lives |

## Relational and Document Models

### Relational Model
**What.** Data organized into relations (tables) of tuples (rows) with a fixed schema. Relationships are expressed via foreign keys and resolved at query time through joins. SQL provides a declarative interface that separates logical query from physical execution.
**Use when.** Your data has many-to-many relationships, you need ad-hoc queries, or you require ACID transactions across multiple entities. Nearly all OLTP workloads start here (PostgreSQL, MySQL, SQL Server).
**Advantages.**
- Join support makes many-to-many relationships natural without data duplication
- Declarative queries allow the optimizer to choose execution strategy
- Mature ecosystem: decades of tooling, indexing strategies, and operational knowledge
**Tradeoffs.**
- Object-relational impedance mismatch: application objects rarely map 1:1 to flat rows, requiring ORM layers or manual mapping
- Schema changes (ALTER TABLE) can be expensive on large tables, especially in MySQL
- Horizontal scaling requires sharding, which breaks cross-shard joins
**Staff signal.** The relational model isn't inherently unscalable — systems like Spanner and CockroachDB prove relational semantics work at global scale. The limitation is *arbitrary joins across partitions*, not the model itself.

### Normalization and Denormalization
**What.** Normalization (1NF: atomic values; 2NF: no partial key dependencies; 3NF: no transitive dependencies) eliminates redundancy so that each fact is stored once, updated in one place. Denormalization deliberately re-introduces redundancy (duplicating data, pre-computing joins) to avoid expensive joins at read time.
**Use when.** Normalize by default for write-heavy or consistency-critical workloads. Denormalize when read patterns are predictable, joins are too expensive, and you can tolerate update complexity.
**Advantages.**
- Normalization: consistency, smaller storage, simpler updates
- Denormalization: faster reads, avoids joins, suits read-heavy access patterns
**Tradeoffs.**
- Denormalization creates update anomalies — a single fact change requires updating every copy
- Over-normalization leads to multi-table joins for simple reads, hurting latency
**Staff signal.** In system design interviews, denormalization should be a deliberate choice with a stated update strategy (async fan-out, eventual consistency, materialized views) — never accidental duplication.

### Document Model
**What.** Data stored as self-contained documents (JSON-like structures with nesting). The document is the unit of atomicity and locality — fields that are accessed together are stored together. Schema-on-read means the database doesn't enforce structure; the application interprets the data upon reading.
**Use when.** Your data is naturally hierarchical (a user profile with nested addresses, preferences, history), access patterns are document-at-a-time (fetch whole profile), and relationships between documents are rare. MongoDB, Couchbase, and DynamoDB (in its document mode) are exemplars.
**Advantages.**
- Excellent locality: one read fetches the entire document without joins
- Flexible schema adapts easily to evolving application requirements
- Maps naturally to application objects, reducing impedance mismatch
**Tradeoffs.**
- Many-to-many relationships are awkward — you either denormalize (duplicating data into each document) or perform application-side joins
- Large documents that are partially updated still incur full-document rewrites in many engines
- Schema-on-read pushes validation burden to every reader, risking silent corruption
**Staff signal.** Document databases do have schema — it's just implicit in application code. This makes breaking changes harder to detect because there's no ALTER TABLE migration; you need application-level versioning.

### Locality of Access
**What.** Storage locality means related data is physically co-located on disk/memory, minimizing I/O operations for common access patterns. The document model wins when you typically read the entire document. It loses when you need only a small subset of fields from many documents (analytics pattern) or when documents grow very large.
**Use when.** Deciding between document and relational based on whether your reads are "whole record" or "slice across many records."
**Advantages.**
- Single-document reads avoid random I/O that multi-table joins require
**Tradeoffs.**
- Writing to part of a document may rewrite the whole thing if the document grows beyond its allocated space
- Analytics queries scanning one column across millions of documents suffer — this is where column-oriented storage wins
**Staff signal.** PostgreSQL's JSONB and relational column groups (e.g., in Spanner) blur the line — you can get document locality within a relational system. The models are converging.

## Graph Models

### Graph Data Models
**What.** Property graph model: vertices (entities with properties) connected by edges (relationships with properties and direction). Triple stores express facts as (subject, predicate, object) triples. Both allow traversing relationships of arbitrary depth and type without pre-defined join paths.
**Use when.** Data has highly interconnected, variable-depth relationships: social networks, fraud detection (transaction chains), knowledge graphs, permissions/access-control graphs, dependency graphs.
**Advantages.**
- Multi-hop traversals (friend-of-friend, shortest path, cycle detection) are natural and efficient
- Adding new relationship types requires no schema migration — just add edges
- Query languages (Cypher for Neo4j, SPARQL for triple stores) express path patterns concisely
**Tradeoffs.**
- Poor fit for bulk analytics or aggregations across the entire dataset
- Graph databases are harder to partition (highly connected subgraphs resist clean cuts)
- Less mature tooling and operational ecosystem compared to relational
**Staff signal.** Know when *not* to use a graph DB: if your "graph" queries are always 1-2 hops deep with a known structure, a relational database with proper indexing and recursive CTEs handles it fine at lower operational cost.

### Graph DB vs Recursive SQL CTEs
**What.** PostgreSQL's `WITH RECURSIVE` allows graph traversals in SQL. For shallow, predictable traversals (org hierarchy, BOM explosion), this avoids introducing a separate database. True graph DBs (Neo4j, Amazon Neptune) justify themselves for variable-depth traversals, complex path expressions, or when the graph is the primary access pattern.
**Use when.** Deciding whether to introduce a specialized graph store or use your existing relational DB.
**Advantages.**
- CTEs avoid operational overhead of a separate system for simple cases
- Graph DBs provide specialized indexing (adjacency lists) and query optimizers for traversal
**Tradeoffs.**
- Recursive CTEs can be slow for deep or wide graphs (no traversal-specific optimization)
- Graph DBs add deployment, backup, and consistency complexity
**Staff signal.** If the graph is an auxiliary access pattern on otherwise relational data, use CTEs. If the graph IS the data model and most queries are traversals, a graph DB earns its keep.

## Other Data Models

### Network/Hierarchical Models (Historical Context)
**What.** Before relational (1960s–70s), CODASYL/network model and IMS hierarchical model represented data as trees or graphs navigated via pointers. Access required knowing the physical path. The relational model's key insight was separating logical queries from physical access paths.
**Use when.** Understanding why declarative query languages matter — the history demonstrates the cost of coupling queries to physical layout.
**Advantages.**
- Historical context explains why the relational model won (physical data independence)
**Tradeoffs.**
- Navigational access meant application code broke when data layout changed
**Staff signal.** Document databases partially re-introduce hierarchical storage, but with flexible schemas and application-side joins rather than hard-coded navigation paths.

### Wide-Column Model (Column Families)
**What.** Data organized by row key, grouped into column families. Within a family, columns are dynamically created per row (sparse). Cassandra and HBase follow this model. Not the same as column-oriented storage (which stores all values of a single column together for analytics). Here, a row's columns are stored together within a family.
**Use when.** High write throughput, append-heavy workloads with known row-key access patterns (time-series by device ID, event logs by user). Access is row-key-centric; range scans within a partition are efficient.
**Advantages.**
- Excellent write performance (append-only, LSM-based internals)
- Elastic horizontal scaling with consistent hashing
- Flexible schema per row within a column family
**Tradeoffs.**
- No joins, no multi-row transactions (Cassandra), limited secondary indexing
- Data modeling is query-driven (you duplicate data to serve different access patterns)
- Operational complexity (compaction tuning, tombstone management)
**Staff signal.** In Cassandra, you design tables around queries, not entities. This means accepting denormalization as the norm, not the exception. If you need multiple access patterns, you create multiple tables with the same data.

### Key-Value Model
**What.** Simplest model: opaque value indexed by a unique key. The database treats the value as a blob — all semantics are in the application. Redis (in-memory), DynamoDB (when used without secondary indexes), and Memcached are exemplars.
**Use when.** Access patterns are purely by primary key (session storage, caching, feature flags, config storage), and you need extremely high throughput with low latency.
**Advantages.**
- Maximum performance: O(1) lookups with minimal overhead
- Simple to partition (hash the key)
**Tradeoffs.**
- No querying by value content — only exact key lookup
- Complex access patterns require application-side logic or secondary stores
**Staff signal.** DynamoDB blurs key-value and document models — it's a key-value store that allows structured documents as values and secondary indexes. Pure key-value stores (Memcached) offer no such features but are faster.

### Time-Series Data Model
**What.** Data points indexed primarily by timestamp, typically append-only (immutable once written), with very high write rates and time-ranged reads. InfluxDB, TimescaleDB (extension on PostgreSQL), and Prometheus are exemplars.
**Use when.** Metrics, monitoring, IoT sensor data, financial tick data — anything where the primary dimension is time.
**Advantages.**
- Optimized for sequential writes and time-range queries
- Aggressive compression exploiting temporal ordering (delta encoding, run-length)
- Automated retention policies and downsampling
**Tradeoffs.**
- Poor for random updates or relational queries
- Cardinality explosions (too many unique tag combinations) degrade performance dramatically
**Staff signal.** High cardinality is the number-one operational challenge in time-series databases. Each unique combination of labels/tags creates a new series, and many TSDBs scale poorly past millions of active series.

## Query Language Models

### Declarative vs Imperative Query Languages
**What.** Declarative (SQL, Cypher): you specify *what* you want; the engine decides *how* to retrieve it. Imperative (CODASYL navigation, manual cursor iteration): you specify the exact steps. Declarative queries enable query optimization, parallelization, and surviving physical layout changes.
**Use when.** Understanding why SQL dominates — it decouples application logic from storage engine internals.
**Advantages.**
- Declarative: optimizer adapts to data statistics, new indexes benefit existing queries without code changes
- Imperative: full control when the optimizer makes poor choices (rare but real)
**Tradeoffs.**
- Declarative requires a good optimizer; bad plans can be hard to diagnose and fix
**Staff signal.** MapReduce is somewhere in between — you write map/reduce functions (somewhat imperative) but the framework handles distribution and fault tolerance (declarative about execution).

### MapReduce as a Programming Model
**What.** A computation is expressed as a stateless `map` function (extracts key-value pairs from each record) and a stateless `reduce` function (aggregates all values for a given key). The framework distributes, shuffles, sorts, and retries. Not a query language per se, but a dataflow programming model.
**Use when.** Understanding batch-processing foundations (Hadoop). Modern systems (Spark, Flink) supersede raw MapReduce but inherit its concepts.
**Advantages.**
- Fault-tolerant: any failed mapper/reducer is simply re-run on the same input
- Horizontally scalable to arbitrary data sizes
**Tradeoffs.**
- Verbose compared to SQL for most analytical queries
- Intermediate data written to disk between stages (slow); Spark improved this with in-memory DAGs
**Staff signal.** MapReduce is largely historical for new designs, but the concept of idempotent, stateless transformations over partitioned data remains foundational for all distributed batch and stream processing.

## Encoding and Schema Evolution

### Encoding Formats
**What.** Serialization translates in-memory objects to bytes for storage/transmission. JSON: human-readable, no schema enforcement, number precision issues (no distinction between int and float in many parsers), verbose. CSV: no schema, delimiter ambiguity. XML: verbose, complex. Binary formats (MessagePack, BSON): more compact JSON-like encoding. Schema-driven binary (Protocol Buffers, Thrift, Avro): compact, strongly typed, support schema evolution.
**Use when.** Choosing the wire format for inter-service communication or long-term storage. For internal services with high throughput, Protobuf/Avro dominate. For public APIs, JSON remains standard.
**Advantages.**
- Schema-driven formats are 3-10× smaller than JSON and faster to parse
- Schema itself serves as documentation and contract between services
**Tradeoffs.**
- Binary formats require schema distribution and aren't human-readable for debugging
- JSON's flexibility is an advantage for rapid prototyping and public APIs
**Staff signal.** Avro's unique advantage is that the reader doesn't need the exact writer's schema at compile time — it resolves differences at read time using schema resolution rules. This makes Avro ideal for data lakes where data from many schema versions coexists.

### Schema Evolution and Compatibility
**What.** *Backward compatible*: new code can read old data (new reader, old writer). *Forward compatible*: old code can read new data (old reader, new writer). *Full compatibility*: both directions. Protobuf/Thrift use field tags (numbers) — new fields get new tags, old code ignores unknown tags (forward); required fields can't be removed (backward). Avro uses a schema registry and resolution rules between writer schema and reader schema.
**Use when.** Any system that undergoes rolling upgrades or stores data long-term (database records written months ago must be readable by today's code).
**Advantages.**
- Enables zero-downtime rolling deploys (old and new code coexist temporarily)
- Long-term storage remains readable as schemas evolve
**Tradeoffs.**
- Cannot remove required fields, rename fields freely, or change field types arbitrarily
- Requires discipline: schema review becomes a deployment gate
**Staff signal.** During a rolling deploy, both old and new code versions run simultaneously. New→old writes need forward compatibility; old→new reads need backward compatibility. You need *both* directions to safely deploy. This is the critical interview insight.

### Dataflow Modes
**What.** Three patterns for data to flow between processes: (1) *Through databases*: writer encodes, reader decodes — schema evolution via backward compatibility. (2) *Through services (REST/gRPC/RPC)*: request/response between client and server — need forward+backward compatibility. (3) *Through async message passing* (Kafka, RabbitMQ): producer and consumer decoupled in time — similar compatibility needs as services but with added temporal decoupling.
**Use when.** Choosing integration patterns between components or services.
**Advantages.**
- Message passing adds buffering, retry, and decoupling that synchronous calls lack
- Services allow independent deployment and scaling
**Tradeoffs.**
- Databases as integration point create tight coupling to schema without explicit contracts
- Async messaging adds debugging complexity (non-deterministic ordering, dead-letter queues)
**Staff signal.** "Database as the integration layer" (shared mutable state) is an anti-pattern at scale because it creates invisible coupling. Explicit service contracts or event schemas make dependencies visible and versionable.

### Rolling Upgrades and Compatibility Direction
**What.** In a rolling upgrade, you replace instances one at a time. During the transition window, old-version instances and new-version instances coexist. New code must read data/messages written by old code (backward compatibility). Old code must handle data/messages written by new code without crashing (forward compatibility — typically by ignoring unknown fields).
**Use when.** Deploying any system that can't afford downtime for upgrades.
**Advantages.**
- Zero-downtime deploys; canary and blue-green strategies depend on this
**Tradeoffs.**
- Schema/protocol changes must be carefully staged (first deploy code that tolerates new format, then deploy code that writes new format)
**Staff signal.** A common mistake is adding a required field and deploying new writers before all readers are updated — old readers crash on the unknown required field. Always deploy readers first in a two-phase approach.

## Analytical Storage Paradigms

### Data Lake / Lakehouse / Warehouse
**What.** *Data warehouse*: structured, schema-on-write analytical store optimized for SQL queries (Snowflake, BigQuery, Redshift). *Data lake*: raw storage of any format (Parquet, JSON, logs) on cheap object storage (S3, ADLS), schema applied at read time. *Lakehouse*: combines lake storage (cheap, open formats like Parquet/Delta Lake) with warehouse features (ACID, SQL, indexing). Examples: Databricks Delta Lake, Apache Iceberg on S3.
**Use when.** Choosing where analytical/ML data lands.
**Advantages.**
- Warehouse: fastest queries, governed, strongly typed
- Lake: cheapest, most flexible, retains raw data
- Lakehouse: cost of lake + usability of warehouse
**Tradeoffs.**
- Warehouses are expensive per-TB; lakes become "data swamps" without governance
- Lakehouse tooling is still maturing relative to established warehouses
**Staff signal.** The trend is lakehouse: open formats (Parquet + Iceberg/Delta) on object storage, queried by warehouse-grade engines. This avoids vendor lock-in and the costly ETL from lake to warehouse.

## Common interview traps

- Using "schema-less" to describe document databases — they have implicit schemas; the correct term is schema-on-read.
- Choosing a graph database for data that's accessed by primary key 99% of the time — operational cost not justified.
- Forgetting that Protobuf field *numbers* (tags) are the compatibility anchor, not field *names*. Renaming a field is safe; changing its tag is not.
- Confusing wide-column (Cassandra) with column-oriented storage (Parquet, Redshift) — they solve different problems.
- Assuming JSON is "good enough" for inter-service communication without considering the 3-10× bandwidth and parsing overhead at scale.
- Ignoring the temporal coexistence problem during rolling deploys — both compatibility directions are needed simultaneously.
- Over-normalizing for a read-heavy system that does the same three-table join on every request.
- Choosing a data model before understanding access patterns — model must be driven by queries.

## Drill questions

1. You have a social network where users have posts, each post has comments, and users can like any comment. Would you model this as a document, relational, or graph? Why? What breaks in each alternative?
2. You're adding a new optional field to a Protobuf message used in a system with rolling deploys. Walk through what happens if old readers encounter the new field. What if the new field were required?
3. When would you choose Avro over Protocol Buffers for a Kafka topic's message format?
4. Explain why wide-column stores like Cassandra require you to model data around queries rather than entities. What happens if you try to use it like a relational database?
5. A team proposes using MongoDB for an e-commerce system with products, orders, inventory, and suppliers. What concerns would you raise?
6. Your system stores user activity events (billions/day) that need to be queried by user_id, by time range, and by event type. Which data model and why?
7. How does schema-on-read in a data lake become a problem at scale? What does a lakehouse add?
8. Describe a scenario where denormalization is the correct choice and explain the update strategy you'd use to maintain consistency.
9. During a rolling deploy, new code writes a message with a new field. Old code reads it and re-writes it without the field. What data is lost? How do you prevent this?
10. When would recursive SQL CTEs be preferable to a graph database for traversal queries?
