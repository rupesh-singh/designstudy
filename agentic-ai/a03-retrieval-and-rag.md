# A3. Retrieval & RAG Architecture

RAG is an information-retrieval system with an LLM attached — not the other way
around. Most RAG failures in production are retrieval failures: the right chunk
was never found, or a wrong chunk was returned and the model faithfully
summarized garbage. Treating RAG as a retrieval engineering problem first, and a
generation problem second, is the orientation that separates working systems from
demo-quality prototypes. This file covers the full pipeline from ingestion to
citation, including the operational concerns (access control, freshness,
multi-tenancy, evaluation) that make or break a production deployment.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| RAG motivation | Why retrieve rather than fine-tune or stuff | Deciding whether RAG is the right architecture |
| End-to-end pipeline | Ingest → chunk → embed → index → retrieve → rerank → generate → cite | Designing or debugging a RAG system |
| Chunking strategies | Splitting documents into retrievable units | Tuning retrieval precision and recall |
| Embeddings | Dense vector representations for semantic similarity | Building or selecting embedding models |
| Vector indexes | HNSW, IVF, PQ — approximate nearest neighbour structures | Choosing index type for recall/latency/memory tradeoff |
| Vector DB vs vector capability | Build/buy decision for vector storage | Deciding whether to add a new datastore |
| Metadata filtering | Pre- or post-filtering by structured attributes | Adding faceted search to retrieval |
| Hybrid search | Dense + sparse/BM25 fusion | Improving recall with complementary signals |
| Reranking | Cross-encoder second-stage scoring | Improving precision after initial retrieval |
| Query understanding | Rewriting, expansion, decomposition, HyDE | Fixing the retrieval query, not the retrieval index |
| Agentic retrieval | Agent decides what to search iteratively | Complex information needs requiring multiple queries |
| GraphRAG / structured retrieval | Graph or SQL-based retrieval | Relational or structured data; when vectors are wrong |
| Access control in retrieval | Per-user permission filtering | Multi-user systems with data sensitivity |
| Freshness & reindexing | Incremental updates, embedding model migration | Keeping the index current, handling model changes |
| Citation & attribution | Linking generated claims to source chunks | Verifiability and trust |
| Retrieval evaluation | Recall@k, MRR, NDCG, groundedness | Measuring retrieval vs generation quality separately |
| Failure taxonomy | Classification of RAG failure modes | Debugging production RAG issues |
| Long context vs RAG vs fine-tuning | Decision framework for grounding strategies | Choosing the right approach for your data scale |
| Caching in RAG | Embedding, retrieval, and response caches | Reducing latency and cost |
| Multi-tenant RAG | Per-tenant index isolation | SaaS applications with tenant data separation |

---

## Foundations

### RAG motivation
**What.** Retrieval-augmented generation grounds an LLM's output in retrieved source material rather than relying solely on the model's parametric knowledge. The core motivations are: grounding (reducing hallucination), freshness (the index is updated without retraining), access control (retrieve only what the user is permitted to see), and cost (retrieval is cheaper than fine-tuning and more scalable than context stuffing).
**Use when.** The model needs knowledge that is too large to fit in the context, too dynamic for fine-tuning, too sensitive for one-size-fits-all access, or simply not in the model's training data.
**Advantages.**
- Grounds output in verifiable sources; enables citation
- Knowledge updates are index operations, not model training runs
- Naturally supports per-user access control at retrieval time
**Tradeoffs.**
- Adds a full retrieval pipeline (ingestion, indexing, querying) to your system
- Retrieval quality is the ceiling on generation quality — the model can only use what it receives
- Introduces latency from the retrieval step (embedding query + index lookup + reranking)
**Staff signal.** RAG is often presented as a hallucination fix. It is not — it is a *grounding* mechanism. The model can still hallucinate even with perfect retrieval if the prompt doesn't force it to stay faithful to the sources. You need both good retrieval *and* good prompt engineering (e.g., "answer only based on the provided context").

### The end-to-end RAG pipeline
**What.** The full pipeline: (1) *Ingest* — acquire source documents; (2) *Chunk* — split into retrievable units; (3) *Embed* — convert chunks to vectors; (4) *Index* — store in a searchable structure; (5) *Retrieve* — find relevant chunks for a query; (6) *Rerank* — reorder by relevance using a more expensive model; (7) *Assemble context* — format retrieved chunks into the prompt; (8) *Generate* — LLM produces the answer; (9) *Cite* — attribute claims to source chunks.
**Use when.** Building, debugging, or evaluating any RAG system. Each stage is independently tunable and independently testable.
**Advantages.**
- Separating stages allows independent optimization and debugging (is the problem in retrieval or generation?)
- Each stage can be swapped: different chunking strategies, different embedding models, different rerankers
**Tradeoffs.**
- End-to-end latency is the sum of all stages; each stage adds cost
- More stages means more things to monitor, test, and maintain
**Staff signal.** When a RAG system produces bad answers, the diagnostic process is: (1) Were the right chunks retrieved? (check retrieval) (2) Were the right chunks ranked highly? (check reranking) (3) Were the chunks used by the model? (check prompt assembly and generation). Most failures are at step 1. Always evaluate retrieval quality independently of generation quality.

---

## Ingestion and indexing

### Chunking strategies
**What.** Chunking splits source documents into units that can be independently retrieved. Strategies include: *fixed-size* (e.g., 512 tokens with overlap), *recursive/structural* (split by headings, paragraphs, sections), *semantic* (split at topic boundaries using embeddings), and *late chunking* (embed the full document first, then chunk the embeddings). Chunk size is a precision/recall lever: small chunks give precise retrieval but miss surrounding context; large chunks provide more context but are noisier and consume more token budget.
**Use when.** Designing or tuning the ingestion pipeline; diagnosing retrieval precision/recall issues.
**Advantages.**
- Structural chunking preserves document organization (a heading stays with its content)
- Overlap between chunks prevents information loss at boundaries
**Tradeoffs.**
- Too-small chunks lose context ("revenue grew 30%" without knowing what revenue)
- Too-large chunks waste token budget and may contain irrelevant passages
- Semantic chunking adds an embedding step during ingestion, increasing ingestion cost
**Staff signal.** There is no universally best chunk size. The right size depends on the query type: factoid Q&A benefits from small, precise chunks (128–256 tokens); summarization benefits from larger chunks (512–1024 tokens). For heterogeneous query patterns, consider storing multiple chunk sizes (a "matryoshka" approach) and selecting at query time based on query type.

### Embeddings
**What.** Embedding models convert text into dense vectors in a high-dimensional space (typically 256–3072 dimensions) where semantic similarity corresponds to vector proximity. The choice of embedding model, dimensionality, and normalization directly affects retrieval quality, index size, and query latency.
**Use when.** Building the core of any dense retrieval system; choosing an embedding model for your domain.
**Advantages.**
- Enables semantic search — "broken screen" matches "cracked display" even with no lexical overlap
- Modern embedding models are fast and relatively cheap compared to LLM inference
**Tradeoffs.**
- Embedding quality degrades on out-of-domain text; a model trained on web text may underperform on legal or medical documents
- Higher dimensionality improves representational capacity but increases storage, memory, and query cost proportionally
- Changing the embedding model requires re-embedding your entire corpus — a potentially expensive migration
**Staff signal.** Embedding model migration is one of the most underestimated operational costs in RAG. When you switch models (and you eventually will, as better ones emerge), you must re-embed every document and rebuild every index. Design for this from day one: track which embedding model produced each vector, and build ingestion pipelines that can reprocess the full corpus.

### Vector indexes: HNSW, IVF, product quantization
**What.** Vector indexes enable approximate nearest neighbour (ANN) search at scale. *HNSW* (Hierarchical Navigable Small World) builds a layered graph — high recall, fast query, but high memory (stores full vectors in memory). *IVF* (Inverted File Index) partitions vectors into clusters — lower memory, but recall depends on probing enough clusters. *Product quantization (PQ)* compresses vectors to reduce memory at the cost of recall. These can be combined (e.g., IVF-PQ).
**Use when.** Choosing index type for your scale, latency, and recall requirements.
**Advantages.**
- HNSW offers excellent recall (>95%) with sub-millisecond queries for millions of vectors
- PQ can reduce memory 4–16× while maintaining usable recall for many applications
**Tradeoffs.**
- HNSW has high memory consumption: for 10M vectors at 1536 dimensions, each vector is ~6KB, so ~60GB in memory
- IVF has lower recall if too few clusters are probed; needs tuning
- PQ introduces lossy compression; fine-grained similarity distinctions are lost
**Staff signal.** Below ~100K vectors, brute-force exact search is fast enough and simpler to operate. Don't introduce ANN complexity until you need it. When you do, HNSW is the default choice for quality-sensitive workloads; IVF-PQ is for cost-sensitive workloads at large scale where you can tolerate some recall loss.

### Vector database vs vector capability in an existing datastore
**What.** You can use a purpose-built vector database (Pinecone, Weaviate, Qdrant, Milvus, etc.) or add vector search to your existing database (PostgreSQL with pgvector, Elasticsearch with dense vectors, MongoDB Atlas Vector Search, etc.). This is a build/buy decision with infrastructure and operational implications.
**Use when.** Deciding on your vector storage strategy.
**Advantages.**
- Purpose-built vector DBs are optimized for ANN query performance, filtering, and scale
- Adding vector capability to an existing store avoids a new infrastructure dependency and keeps data co-located with metadata
**Tradeoffs.**
- A new vector DB is another service to operate, backup, monitor, and secure
- Existing-store vector support may have limited indexing options, lower query performance, or weaker filtering
**Staff signal.** The decision often comes down to operational complexity vs performance. If your retrieval corpus is <1M chunks and you already run PostgreSQL, pgvector is usually sufficient and saves you an entire new infrastructure component. If you're at 10M+ chunks with sub-10ms latency requirements, a purpose-built vector DB earns its keep.

---

## Retrieval quality

### Metadata filtering: pre- vs post-filtering
**What.** Metadata filtering restricts retrieval results by structured attributes (date, source, category, user_id). *Pre-filtering* narrows the search space before ANN search. *Post-filtering* runs ANN search over all vectors and then filters results. The choice affects both recall and performance.
**Use when.** Any RAG system with structured metadata that should constrain results (date ranges, document types, tenant IDs, permissions).
**Advantages.**
- Pre-filtering is fast and avoids wasting search effort on irrelevant vectors
- Enables complex faceted search (category = "billing" AND date > 2025-01-01)
**Tradeoffs.**
- Post-filtering has a *recall trap*: if you retrieve top-10 and then filter by metadata, you may be left with fewer than 10 (or zero) relevant results because the top ANN results were filtered out
- Pre-filtering can be slower if the metadata filter is very selective (small partition in a large index)
**Staff signal.** Post-filtering is the default but it silently destroys recall. If you ask for top-10 and post-filter to 3 results, you missed 7 potentially relevant chunks that were in the right metadata partition but outside the ANN top-10. Pre-filtering or hybrid approaches (filter-then-search) are almost always better for recall-sensitive applications.

### Hybrid search: dense + sparse/BM25; reciprocal rank fusion
**What.** Hybrid search combines dense (embedding-based) retrieval with sparse (keyword-based, typically BM25) retrieval. *Reciprocal rank fusion (RRF)* merges the two ranked lists by combining the reciprocal of each result's rank across both methods. This captures both semantic similarity and exact keyword matches.
**Use when.** Improving retrieval recall, especially when queries contain domain-specific terms, product names, or codes that dense retrieval misses.
**Advantages.**
- Sparse retrieval catches exact matches that embedding models miss (part numbers, acronyms, proper nouns)
- Dense retrieval catches semantic matches that keyword search misses
- RRF is parameter-free and works well without tuning
**Tradeoffs.**
- Maintaining two indexes (vector + inverted) doubles indexing cost and complexity
- Query latency is the max of the two retrieval paths plus merge time
**Staff signal.** Pure dense retrieval fails on *entity-rich* queries ("error code ERR_12345" or "invoice #A-2024-7891") because embedding models compress these into generic semantic space. Pure sparse retrieval fails on *semantic* queries ("why is my bill so high"). Hybrid search is the production default for any non-trivial RAG system. If you're only using dense retrieval, you're leaving recall on the table.

### Reranking with cross-encoders
**What.** Reranking is a two-stage retrieval approach: first, a fast retriever (embedding similarity or BM25) returns a broad set of candidates (e.g., top-50). Then, a cross-encoder reranker — which processes the query and each candidate *together* rather than independently — scores and reorders them. Cross-encoders are more accurate but far slower than bi-encoders.
**Use when.** Retrieval precision matters more than latency budget, or initial retrieval recall is high but precision is low.
**Advantages.**
- Cross-encoders significantly improve ranking quality by modeling query-document interaction
- Only runs on the candidate set, not the full corpus, so cost is bounded
**Tradeoffs.**
- Adds latency proportional to the number of candidates reranked (each is a model inference)
- The reranker is a separate model to deploy, version, and monitor
**Staff signal.** Reranking is the highest-ROI improvement for most RAG systems that have decent recall but inconsistent relevance in the top results. The economics: retrieving top-50 with a fast bi-encoder, then reranking to top-5 with a cross-encoder, typically adds only 50–200ms but can improve answer quality substantially. Size the candidate set to balance recall against reranking cost.

### Query understanding: rewriting, expansion, decomposition, HyDE, multi-query
**What.** Query understanding transforms the user's raw query into one or more retrieval-optimized queries. *Rewriting* rephrases for clarity. *Expansion* adds synonyms or related terms. *Decomposition* splits a complex question into sub-questions. *HyDE* (Hypothetical Document Embeddings) generates a hypothetical answer and embeds that instead of the query. *Multi-query* generates multiple query variants and retrieves for each.
**Use when.** User queries are vague, ambiguous, or use different vocabulary than the source documents.
**Advantages.**
- Bridges the vocabulary gap between how users ask and how documents are written
- Decomposition enables retrieval for complex, multi-part questions
**Tradeoffs.**
- Each technique adds an LLM call (latency + cost) before retrieval even begins
- Query expansion can introduce drift — broadening the query too much retrieves irrelevant results
- Multi-query multiplies retrieval cost by the number of variants
**Staff signal.** Query understanding is where LLM calls add the most retrieval value. A single HyDE or rewrite call before retrieval often improves recall more than any amount of index tuning. But budget it: if you're adding three LLM calls (decompose + expand + rewrite) before every retrieval, the latency and cost may exceed the benefit. Start with one technique (rewriting is the safest default), measure its impact, and add others only if needed.

### Agentic/iterative retrieval
**What.** Instead of a single retrieve-then-generate pass, the agent decides what to search for, retrieves results, evaluates whether it has enough information, and decides whether to issue additional queries. The agent treats retrieval as a tool it can call multiple times with different queries.
**Use when.** Complex information needs where a single query cannot capture all required information, or where the first retrieval result informs what to search next.
**Advantages.**
- Handles multi-faceted questions that require information from multiple documents or topics
- Self-corrects: if the first retrieval is insufficient, the agent can refine the query
**Tradeoffs.**
- Multiple retrieval + LLM reasoning steps multiply latency and cost
- The agent may loop inefficiently, re-querying with minor variations
- Requires the agent to have good judgment about when to stop retrieving
**Staff signal.** Agentic retrieval is powerful but must be bounded: set a maximum number of retrieval iterations (3–5 is typical) and a total token budget for the retrieval phase. Without bounds, an agent chasing an answer that doesn't exist in the corpus will loop until timeout, burning tokens and latency.

### GraphRAG and structured/relational retrieval
**What.** GraphRAG overlays a knowledge graph on top of document chunks, capturing entities and relationships. Structured retrieval uses SQL or graph queries against structured data instead of (or alongside) vector search. This is critical when the answer depends on relationships ("who reports to whom"), aggregations ("total revenue last quarter"), or joins across data sources.
**Use when.** The information need is relational, aggregative, or requires traversing connections that flat vector search cannot represent.
**Advantages.**
- Graph traversal and SQL queries are precise and deterministic — they don't "miss" like vector search
- Captures structural relationships that embedding similarity cannot represent
**Tradeoffs.**
- Building and maintaining a knowledge graph is expensive and labor-intensive
- Graph construction from unstructured text is error-prone (entity extraction and relation extraction have their own failure modes)
**Staff signal.** The most common staff-level point: *vector search is the wrong tool for structured queries*. "What were our top 5 customers by revenue last quarter?" should be a SQL query, not a vector search. A well-designed RAG system routes queries to the right retrieval backend — vector for semantic questions, SQL for structured questions, graph for relational questions. This routing decision is itself a classification problem.

---

## Production operations

### Access control in retrieval
**What.** In multi-user systems, retrieval must respect per-user permissions — a user must only see documents they are authorized to access. Enforcement can be at *index time* (separate indexes per permission group) or *query time* (filter by user's permissions during retrieval). The failure mode is a data leak: a user sees content from a document they shouldn't have access to.
**Use when.** Any RAG system where users have different access levels — which is almost every enterprise deployment.
**Advantages.**
- Index-time enforcement is simpler and has no query-time overhead
- Query-time filtering is more flexible for fine-grained, changing permissions
**Tradeoffs.**
- Index-time enforcement means duplicating or partitioning indexes; permission changes require re-indexing
- Query-time filtering has the post-filter recall trap (see metadata filtering) and must be rigorously tested
- Permission models can be complex (group memberships, inherited permissions, time-limited access)
**Staff signal.** Access control in RAG is a data-security problem masquerading as a search problem. The most dangerous failure mode is a chunk from a confidential document appearing in a response to an unauthorized user. Always test this explicitly with adversarial queries. Default to index-time isolation (per-tenant indexes) for simplicity and security; use query-time filtering only when the permission model is too dynamic for index-time partitioning.

### Freshness: incremental indexing, deletes, embedding model migration
**What.** Keeping the index current requires handling document additions, updates, and deletes. Incremental indexing adds or updates changed documents without re-embedding the entire corpus. Deletes require tombstones or hard removal to prevent stale content from being retrieved. Changing the embedding model requires re-embedding the *entire* corpus — this is an expensive, often underestimated migration.
**Use when.** Operating any RAG system over time, not just building one.
**Advantages.**
- Incremental indexing minimizes re-embedding cost for frequently updated corpora
- Proper delete handling prevents stale or retracted content from appearing in answers
**Tradeoffs.**
- Embedding model migration is the costliest operational event: re-embed everything, rebuild indexes, validate recall, cut over — and you cannot mix vectors from different models in one index
- Tombstones / soft deletes add complexity to garbage collection and index maintenance
**Staff signal.** Plan for embedding model migration from day one. Store the source text alongside the vector so you can re-embed without re-ingesting. Track which embedding model version produced each vector. Build a re-indexing pipeline that can run in the background while serving from the old index, then cut over. This is the operational equivalent of a database migration, and it is just as painful if not planned for.

### Citation and attribution
**What.** Citation links each claim in the generated output to the specific source chunk(s) that support it. This enables users to verify the answer and builds trust. Implementation approaches: instruct the model to cite by chunk ID, use constrained output to include citation markers, or post-process to match generated sentences to source chunks via similarity.
**Use when.** Any RAG system where users need to trust or verify the output — most enterprise and knowledge-management use cases.
**Advantages.**
- Enables users to verify claims without trusting the model blindly
- Provides an audit trail for compliance-sensitive applications
**Tradeoffs.**
- Models sometimes cite the wrong source or fabricate citations that look plausible
- Post-hoc citation verification (checking that the cited source actually supports the claim) adds another model call or similarity check
**Staff signal.** Citation is a *verification UX*, not a guarantee of correctness. The model may cite a source that partially supports its claim while omitting contradictory information from another source. Robust citation requires: (1) the model cites specific chunks by ID, (2) the system verifies that the cited chunk actually supports the claim (via similarity or entailment check), (3) the UI links directly to the source so users can verify themselves.

### Retrieval evaluation: recall@k, MRR, NDCG, groundedness
**What.** Retrieval and generation quality must be evaluated *separately*. *Recall@k*: fraction of relevant documents found in the top-k results. *MRR* (Mean Reciprocal Rank): where the first relevant result appears. *NDCG* (Normalized Discounted Cumulative Gain): measures ranking quality accounting for graded relevance. *Groundedness/faithfulness*: whether the generated answer is supported by the retrieved sources (evaluated via LLM-as-judge or entailment models).
**Use when.** Building evaluation pipelines, diagnosing RAG quality issues, comparing retrieval configurations.
**Advantages.**
- Separating retrieval evaluation from generation evaluation tells you *where* the problem is
- Quantitative metrics enable apples-to-apples comparison of chunking strategies, embedding models, and rerankers
**Tradeoffs.**
- Requires a labeled evaluation set (query + relevant documents), which is expensive to create
- Groundedness evaluation using LLM-as-judge is itself noisy and needs calibration
**Staff signal.** The number one diagnostic practice: when a RAG system produces a bad answer, first check if the relevant chunks were retrieved. If they were not, no amount of prompt engineering will fix it — the problem is in retrieval. Evaluate retrieval quality independently, with its own metrics and test set, before tuning generation.

### Failure taxonomy
**What.** RAG failures fall into distinct categories requiring different fixes: (1) *Missed retrieval*: the relevant chunk exists but was not retrieved (embedding or query mismatch). (2) *Wrong chunk*: an irrelevant chunk was retrieved and ranked highly. (3) *Correct chunk, ignored*: the right chunk was in context but the model didn't use it. (4) *Conflicting sources*: multiple chunks disagree and the model picks the wrong one or confabulates. (5) *Stale content*: the chunk is outdated, and the model presents old information as current.
**Use when.** Debugging production RAG issues; building monitoring and alerting.
**Advantages.**
- Categorical diagnosis enables targeted fixes rather than blind prompt tweaking
- Each failure type has a different remediation: better chunking, better reranking, better prompt, better freshness
**Tradeoffs.**
- Diagnosing which failure mode occurred requires logging retrieved chunks, rankings, and generated output — which increases storage and complexity
**Staff signal.** Build logging that captures, for every RAG request: the user query, the rewritten query, the retrieved chunks with scores, the assembled prompt, and the generated output. Without this observability, debugging RAG failures is guesswork. The most common failure is "missed retrieval," and the fix is usually in query understanding or chunking, not in the LLM prompt.

---

## Architecture decisions

### Long context vs RAG vs fine-tuning: the decision framework
**What.** Three strategies for giving a model domain knowledge: *long context* (stuff it in the prompt), *RAG* (retrieve relevant chunks per query), *fine-tuning* (bake it into model weights). The decision depends on corpus size, update frequency, access-control needs, cost, and auditability.
**Use when.** Deciding how to incorporate organizational knowledge into an LLM system.
**Advantages.**
- Long context: simplest; no retrieval pipeline; works for small, static corpora (<100 pages)
- RAG: handles large, dynamic corpora with per-user access control; auditable via citations
- Fine-tuning: best for teaching style, format, or behaviour patterns; no per-request context cost
**Tradeoffs.**
- Long context: cost scales with context size on every request; quality degrades with length; no access control
- RAG: retrieval failures are the quality ceiling; pipeline complexity; latency from retrieval step
- Fine-tuning: expensive training runs; no freshness (frozen at training time); can't cite sources; difficult to update
**Staff signal.** These are not mutually exclusive. A common production pattern: fine-tune a model for your domain's style and vocabulary, use RAG for fresh/dynamic knowledge with access control, and use long context for per-session information (conversation history, current document). The decision is not "which one" but "which layer handles which type of knowledge."

### Caching in RAG
**What.** Caching at multiple levels reduces latency and cost: *embedding cache* (avoid re-embedding identical queries), *retrieval cache* (cache query→chunks mapping for repeated queries), *semantic response cache* (cache similar queries→response, using embedding similarity to match). Each level introduces staleness risk.
**Use when.** High-traffic RAG systems with query patterns that exhibit repetition or clustering.
**Advantages.**
- Embedding cache eliminates the embedding model call for repeated queries — near-zero cost for cache hits
- Retrieval cache skips the entire index search for repeated queries
- Response cache skips everything, returning the full answer instantly
**Tradeoffs.**
- Staleness: cached responses don't reflect index updates; a stale cache can serve outdated answers
- Semantic caching (matching "similar" queries to cached responses) risks returning wrong answers for queries that are semantically close but factually different
- Cache invalidation is hard — when a source document is updated, all cached responses that used it should be invalidated, but tracking this dependency is complex
**Staff signal.** The safest cache is the embedding cache (deterministic, no staleness risk). Retrieval caching is safe with a TTL matched to your index update frequency. Semantic response caching is the most dangerous — "how much does plan A cost?" and "how much does plan B cost?" are semantically similar but have completely different answers. Use semantic caching only for truly identical queries, or accept the staleness risk with short TTLs and user-facing freshness indicators.

### Multi-tenant RAG and per-tenant index isolation
**What.** In SaaS applications, each tenant's data must be isolated in retrieval. Approaches range from *shared index with tenant-ID filtering* (cheapest, highest risk) to *per-tenant indexes* (most isolated, most expensive) to *per-tenant embedding models* (rarely justified). The choice balances cost, security, and operational complexity.
**Use when.** Building any RAG-powered SaaS product with multiple customers.
**Advantages.**
- Per-tenant indexes provide hard isolation — a bug in filtering cannot leak data across tenants
- Shared index with filtering is simpler and cheaper to operate at small scale
**Tradeoffs.**
- Per-tenant indexes multiply infrastructure cost and operational overhead (N indexes to manage, back up, monitor)
- Shared index with filtering relies on the filtering being *correct for every query* — a single bug is a data breach
- Noisy-neighbour effects in shared indexes: one tenant's large corpus can affect search latency for others
**Staff signal.** For enterprise SaaS with sensitive data, default to per-tenant indexes. The operational overhead is real but the data-leak risk of shared-index filtering bugs is worse. For consumer-grade applications with lower sensitivity, shared index with tenant-ID pre-filtering is acceptable — but test the isolation rigorously, including adversarial queries designed to bypass the filter.

---

## Common interview traps

- **"RAG solves hallucination."** RAG provides grounding, but the model can still ignore retrieved content, hallucinate beyond it, or faithfully summarize a wrong chunk. You need retrieval quality + faithful generation + verification.
- **"Just use the biggest context window instead of RAG."** This ignores cost (every request pays for the full context), quality degradation (lost-in-the-middle), access control (everyone sees everything), and freshness (context must be assembled per request anyway).
- **"Vector search is always the right retrieval method."** Structured queries (aggregations, joins, lookups by ID) should use SQL. Entity-rich queries benefit from keyword search. Vector search is for semantic similarity.
- **"Higher-dimensional embeddings are always better."** They improve representational capacity but increase storage, memory, and query cost. For many workloads, 256–768 dimensions perform nearly as well as 1536+ at a fraction of the cost.
- **"Post-filtering is fine for access control."** Post-filtering can silently return fewer results than requested because filtered-out results aren't replaced. For access control, this can also create a side channel — response size leaking the existence of restricted documents.
- **"We just chunk at 512 tokens and it works."** Chunk size is a precision/recall lever that depends on document type and query type. Fixed-size chunking across all content types is a common source of retrieval failures.
- **"Reranking is too slow to use in production."** Reranking 20–50 candidates with a cross-encoder typically adds 50–200ms — well within budget for most applications and often the highest-ROI improvement.
- **"We can change embedding models any time."** Changing embedding models requires re-embedding the entire corpus and rebuilding indexes. It is a migration, not a configuration change.
- **"We evaluate RAG end-to-end."** If you only evaluate the final answer, you cannot tell whether a bad answer was caused by bad retrieval or bad generation. Evaluate retrieval and generation separately.

## Drill questions

1. Your RAG system retrieves the correct chunk for 80% of queries but only 60% of final answers are correct. Where is the problem, and how do you diagnose it?
2. You need to serve a 50M-document corpus with sub-100ms retrieval latency. Walk through your vector index choice, sizing, and infrastructure.
3. Design the access-control layer for a RAG system where users belong to overlapping groups with different document permissions. Compare index-time vs query-time enforcement.
4. Your organization wants to switch from embedding model A to embedding model B (higher quality, different dimensions). Design the migration plan including zero-downtime cutover.
5. A user asks: "What were our top 5 products by revenue last quarter?" Your RAG system returns an answer based on vector-searched marketing documents. What went wrong, and how should the system handle this query?
6. Compare the cost and quality tradeoffs of using a 1M-token context window to ingest 500 pages vs building a RAG pipeline over the same corpus.
7. Your RAG system serves 10 tenants. Tenant A has 100K documents; tenant B has 500. Design the multi-tenant architecture and justify shared vs isolated indexes.
8. The same user query is asked 1,000 times per day by different users with different permissions. Design a caching strategy that balances latency, cost, and data isolation.
9. Your hybrid search (dense + BM25) is returning good results for English queries but poor results for queries containing product codes like "XR-4500-B." Diagnose and fix.
10. An agent-based RAG system is averaging 4 retrieval iterations per query, each adding ~500ms. The product team wants total latency under 2 seconds. What are your options?
11. Design a retrieval evaluation pipeline for a customer-support RAG system. What metrics do you track, how do you build the evaluation dataset, and what thresholds trigger an alert?
12. Your RAG system has a "conflicting sources" problem: two indexed documents give different answers to the same question (an old policy and a new policy). How do you handle this at the retrieval and generation levels?
