# A6. Memory & State Management

The context window is the agent's working memory — fast, expensive, and bounded. Everything beyond that boundary requires a memory system: a deliberate engineering choice about what to persist, how to retrieve it, and when to forget. The core mental model is RAM vs storage: the context window is RAM (fast, volatile, limited), and memory systems are storage (slower, durable, scalable). Getting this design right determines whether an agent can handle a one-shot question, a multi-hour session, a returning user, or a long-lived autonomous workflow. This section covers the full spectrum from in-context history management to persistent cross-session memory, plus the state management patterns that enable durable, resumable agent execution.

## Quick-reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Context window as working memory | RAM analogy for bounded, expensive in-context state | Reasoning about what the model can "see" |
| Short-term / session memory | Managing the current conversation's history | Any multi-turn interaction |
| Conversation summarization | Compacting history to stay within context limits | Sessions exceed context window |
| Hierarchical summarization | Multi-level summaries for very long sessions | Sessions that run for hours or hundreds of turns |
| Long-term memory categories | Episodic, semantic, procedural | Designing cross-session memory |
| Memory extraction | Deciding what and when to write to memory | Automating long-term memory creation |
| Memory storage backends | Vector, relational, hybrid | Choosing where memories live |
| Memory retrieval | Getting the right memory at the right time | Any agent that reads from memory |
| Memory conflicts and updates | Handling changed facts or preferences | Users correct themselves or change their mind |
| Forgetting and deletion | Decay, TTL, GDPR erasure | Unbounded growth, compliance |
| Deduplication | Preventing redundant memories | Memory store grows over time |
| Scratchpad / working notes | Externalizing intermediate state | Agent needs to track state beyond context capacity |
| External state (files, DB, todo lists) | Context-scaling via external storage | Agent tasks exceed context budget |
| Checkpointing and resumability | Persisting agent run state for crash recovery | Multi-step agents with side effects |
| Scoped memory | Session, user, org-level isolation | Multi-user / multi-tenant systems |
| Multi-tenant isolation | Preventing cross-tenant memory leakage | SaaS agent products |
| Cache vs memory | Prompt cache ≠ persistent memory | Avoiding architectural confusion |
| State machines for agents | Explicit state vs implicit context state | Complex agent workflows with defined phases |
| Concurrent session consistency | Memory coherence across parallel sessions | Same user using multiple sessions simultaneously |
| Memory retrieval cost | Latency and token cost per turn | Optimizing agent responsiveness |
| Evaluating memory quality | Measuring recall precision and relevance | Validating that memory is helping, not hurting |
| Privacy and PII in memory | Encryption, access control, compliance | Any production memory system |

## Working memory: context management

### Context window as working memory
**What.** The context window is the model's only "working memory" — it can reason about exactly what is in the current context, nothing more. Everything outside the context is invisible to the model. Context tokens are expensive (paid per call), bounded (finite window size), and volatile (lost when the session ends unless explicitly persisted).
**Use when.** Making any design decision about what information the agent has access to during reasoning.
**Advantages.**
- Simple: whatever is in context is available; no retrieval step needed
- High fidelity: no summarization loss
**Tradeoffs.**
- Expensive at scale: every token in context is paid on every LLM call
- Bounded: context windows range from ~8K to ~1-2M tokens depending on model, but quality degrades well before the limit on many models (the "lost in the middle" phenomenon)
**Staff signal.** Effective context usage is not about fitting more in — it is about putting the right information at the right position. Information at the beginning and end of the context is recalled better than information in the middle. Structure your context with system instructions and critical state at the top, recent history at the bottom, and retrievals/summaries in between.

### Short-term / session memory
**What.** The conversation history within a single session. Management strategies: (1) full history — include every message (works for short sessions), (2) sliding window — keep only the last N messages, (3) summarized history — periodically summarize older messages and replace them with the summary.
**Use when.** Any multi-turn conversation or agent session.
**Advantages.**
- Full history preserves all detail; sliding window keeps cost constant; summarization balances both
**Tradeoffs.**
- Full history costs grow linearly per turn (each call includes the full history). Sliding window loses earlier context. Summarization is lossy — the model decides what to keep, and it may drop information you later need.
**Staff signal.** In production, summarized history is the default for sessions beyond ~10-15 turns. But summarization quality varies — always preserve key artifacts explicitly: decision points, user-stated constraints, entity IDs, and error states. These are what the model most often needs and most often drops.

### Conversation summarization and compaction
**What.** When conversation history approaches the context limit, summarize older portions: a separate (often cheaper) LLM call condenses the older messages into a shorter summary. The summary replaces the original messages in the context. What to preserve: decisions made, constraints stated, entity identifiers, and open questions. What to drop: pleasantries, exploration that led nowhere, redundant restatements.
**Use when.** Sessions that exceed ~50% of the context window.
**Advantages.**
- Extends effective session length without hitting context limits
- Can reduce per-call cost significantly for long sessions
**Tradeoffs.**
- Lossy: summarization inevitably drops detail. The model may later need something that was summarized away.
- The summarization call itself costs tokens and adds latency
**Staff signal.** Use a structured summarization prompt that explicitly enumerates what to preserve (IDs, constraints, decisions, open tasks) rather than a generic "summarize this conversation." Generic summaries lose the details that matter most for task continuity.

### Hierarchical summarization
**What.** For very long sessions (hundreds of turns, multi-hour runs), a single summary becomes too long or too lossy. Hierarchical summarization uses multiple levels: recent messages are kept verbatim, slightly older messages are summarized at a fine grain (per-10-turn summaries), and much older history is summarized at a coarse grain (per-session or per-phase summaries).
**Use when.** Agent sessions that run for many hours or produce hundreds of turns (research agents, long coding sessions, overnight batch agents).
**Advantages.**
- Balances recency detail with historical breadth
**Tradeoffs.**
- Multiple levels of summarization multiply information loss; each level is lossier than the one below
- Implementation complexity: managing multiple summary levels and deciding promotion thresholds
**Staff signal.** The hierarchy maps naturally to time decay: recent = verbatim, medium = detailed summary, old = key facts only. This mirrors how human memory works and, more importantly, matches how agents actually use history — recent context matters far more than distant context.

## Persistent / long-term memory

### Long-term memory categories
**What.** Three categories, borrowed from cognitive science but useful as engineering abstractions: (1) Episodic — records of what happened ("user asked for a refund on order #123 on March 5"), (2) Semantic — facts and preferences ("user prefers dark mode, is on the enterprise plan"), (3) Procedural — learned how-to patterns ("when user asks about billing, check subscription status first, then check payment history").
**Use when.** Designing what to store in cross-session memory.
**Advantages.**
- Clear taxonomy guides what to extract and how to store it
- Different categories benefit from different storage backends (structured for semantic, vector for episodic)
**Tradeoffs.**
- Categories overlap: "user changed their email on June 1" is both episodic and semantic
- Procedural memory is hardest to extract and most dangerous — it can encode biases or outdated procedures
**Staff signal.** Semantic memory (facts/preferences) delivers the highest ROI and is easiest to get right. Start there. Episodic memory is useful for continuity but grows unboundedly. Procedural memory is powerful but risky — it bypasses explicit prompt engineering and is hard to audit or correct.

### Memory extraction
**What.** The process of deciding what to write to long-term memory and when. Approaches: (1) LLM-based extraction — after each turn (or periodically), a model call extracts key facts, preferences, and events from the conversation; (2) explicit user action — the user says "remember that I prefer X"; (3) rule-based triggers — specific events (purchase, preference change) automatically generate memory entries.
**Use when.** Building any long-term memory system.
**Advantages.**
- LLM-based extraction captures implicit information the user didn't explicitly state
- Explicit user action ensures high-precision memories
**Tradeoffs.**
- LLM-based extraction adds cost per turn and may extract wrong or irrelevant information
- Relying only on explicit user action misses most useful memories (users rarely say "remember this")
**Staff signal.** Combine approaches: use rule-based triggers for high-value, well-defined events (purchases, preference settings), LLM-based extraction for implicit information, and user-initiated saves for things the user explicitly calls out. Validate extraction quality by sampling and human review — bad memories are worse than no memories.

### Memory storage backends
**What.** Where memories live. Options: (1) Vector store — memories embedded and retrieved by semantic similarity (good for episodic recall), (2) Relational/structured store — memories as typed records with explicit fields (good for semantic facts: user.plan = "enterprise"), (3) Hybrid — structured data for known schemas, vector store for unstructured.
**Use when.** Choosing the memory infrastructure.
**Advantages.**
- Vector stores handle fuzzy/semantic retrieval well; structured stores handle exact lookups and updates well
**Tradeoffs.**
- Vector stores are poor at exact recall ("what is my email?") — similarity search returns approximately relevant results, not exact matches. Structured stores require predefined schemas and cannot handle novel fact types.
**Staff signal.** Structured memory is underrated. Most high-value agent memories are facts that fit into known schemas (user preferences, account details, past decisions). A simple key-value or relational store with exact lookup outperforms vector search for these. Use vector stores for the genuinely unstructured/fuzzy retrieval cases.

### Memory retrieval
**What.** Getting the right memories into the context at the right time. Retrieval signals: (1) relevance — semantic similarity to the current query, (2) recency — more recent memories weighted higher, (3) importance — some memories flagged as high-value. Retrieval can be triggered by the user's message, by the agent's reasoning, or proactively by the runtime.
**Use when.** Any agent that reads from a memory store.
**Advantages.**
- Good retrieval makes the agent feel like it "knows" the user; dramatically improves user experience
**Tradeoffs.**
- Retrieving too much is a failure mode: irrelevant memories dilute the context and confuse the model. Retrieving too little means the agent forgets important context.
- Retrieval adds latency to every turn
**Staff signal.** Measure retrieval precision, not just recall. An agent that retrieves 20 memories and uses 2 is wasting 18 memories' worth of context tokens. Set a low retrieval count (3-5 memories) and optimize for precision. A memory system that returns the wrong memories is worse than having no memory at all.

### Memory conflicts and updates
**What.** Users change their minds, correct themselves, or provide updated information. The memory system must handle conflicts: when a new memory contradicts an existing one (user's address changed), the old memory should be superseded, not duplicated. Approaches: versioning (keep old with a "superseded" flag), direct overwrite, or timestamped entries with "latest wins" retrieval.
**Use when.** Any long-term memory system for returning users.
**Advantages.**
- Prevents the agent from citing outdated information
**Tradeoffs.**
- Conflict detection is non-trivial: "I prefer dark mode" and "actually, light mode" are semantically opposite but not lexically related enough for simple deduplication
**Staff signal.** For structured memories (known schemas), conflict resolution is straightforward — update the field. For unstructured memories, you need either an LLM-based conflict check on write (expensive) or a recency-biased retrieval strategy that naturally favors newer information. The second approach is simpler and usually sufficient.

### Forgetting, decay, and deletion
**What.** Memories must be removable: by time-based decay (TTL), by explicit deletion (user requests or GDPR right-to-erasure), or by importance-based pruning (low-value memories expire first). Without a forgetting mechanism, memory stores grow unboundedly, retrieval degrades, and stale information pollutes the context.
**Use when.** Any production memory system — this is not optional.
**Advantages.**
- Keeps memory stores manageable; ensures compliance with data regulations
- Prevents stale memories from degrading agent quality
**Tradeoffs.**
- Aggressive decay may delete still-useful memories; conservative decay leads to unbounded growth
- GDPR erasure requires knowing which memories reference a given user, including indirect references
**Staff signal.** GDPR right-to-erasure is the hard constraint that drives your memory architecture. If you cannot enumerate and delete all memories associated with a specific user, you have a compliance problem. Design the data model with deletion in mind from day one — retrofitting is expensive.

### Deduplication
**What.** Over time, memory systems accumulate near-duplicate entries ("user likes dark mode" stored multiple times with slight variations). Deduplication: on write, check for existing memories that are semantically equivalent and merge or skip. On read, deduplicate retrieved results before injecting into context.
**Use when.** Any memory system that accumulates entries over multiple sessions.
**Advantages.**
- Prevents wasting context tokens on redundant information
**Tradeoffs.**
- Semantic deduplication (as opposed to exact string match) requires an embedding comparison or LLM call, adding write-time cost
**Staff signal.** Unbounded memory growth is an operational problem that manifests slowly. Monitor total memory count per user and set alerts on growth rate. Most production memory systems need a deduplication pass within 3-6 months of launch.

## Externalizing state

### Scratchpad / working notes
**What.** The agent writes intermediate state (partial results, task lists, hypotheses) to an external scratchpad — a file, database record, or structured note — rather than keeping it all in the context. The agent reads from the scratchpad when it needs the information, rather than carrying it in every LLM call.
**Use when.** Agent tasks that involve tracking multiple items, partial results, or state that exceeds comfortable context size.
**Advantages.**
- Reduces per-call context size; the agent only loads what it currently needs
- Scratchpad persists across context window boundaries (summarization cannot lose it)
**Tradeoffs.**
- Requires the agent to learn to use the scratchpad tools (read/write); adds tool-call overhead
- Risk of the agent forgetting to check the scratchpad for information it already computed
**Staff signal.** Externalize state proactively for any agent that tracks more than ~5 items or runs for more than ~10 steps. The scratchpad is the agent equivalent of a programmer's notepad — it prevents information loss from summarization and context overflow.

### Externalizing state outside context (files, DB, todo lists)
**What.** A general pattern: when agent state exceeds what fits comfortably in context, move it to external storage and give the agent tools to read/write that storage. This is a context-scaling technique — the agent's effective memory becomes the external store, accessed on demand.
**Use when.** The agent's task involves producing or managing artifacts larger than a few thousand tokens (code files, reports, datasets, project plans).
**Advantages.**
- Breaks the context-window ceiling; agent can work on arbitrarily large artifacts
**Tradeoffs.**
- Adds round-trips for every read/write; the agent must manage external state coherently, which not all models do well
**Staff signal.** This pattern is how coding agents work with entire codebases: they read/write files rather than holding the whole codebase in context. The design challenge is not the storage — it is the retrieval: helping the agent find the right file/section to read at the right time.

### Checkpointing and resumability
**What.** Persisting the agent's execution state (completed steps, accumulated results, current position in the plan) at each step so that after a crash, the agent can resume from the last checkpoint rather than restarting from scratch.
**Use when.** Any agent that runs for more than a few steps or performs side effects.
**Advantages.**
- Prevents wasted work after crashes; avoids re-executing side effects
**Tradeoffs.**
- Checkpoint storage cost; schema evolution if the checkpoint format changes between deployments
**Staff signal.** Checkpoint the action log (what was done and what was returned), not the raw LLM context. On resume, reconstruct the context by replaying the action log through a fresh prompt. This is more robust than serializing the model's conversational state, and it lets you update the system prompt between restarts.

## Scope and isolation

### Session vs user vs organization scoped memory
**What.** Memory scoping determines what the agent can recall: session-scoped memories are visible only within one session, user-scoped memories persist across sessions for one user, organization-scoped memories are shared across users in an organization.
**Use when.** Designing the memory access model for any multi-user system.
**Advantages.**
- User-scoped memory enables personalization; org-scoped memory enables shared knowledge (company policies, shared FAQs)
**Tradeoffs.**
- Broader scope increases leakage risk; org-scoped memories may expose information to users who shouldn't see it
- Cross-scope retrieval requires careful access control
**Staff signal.** Default to user scope. Org-scoped memory is valuable but requires the same access-control rigor as any shared data store. Ask: "would you put this in a shared database with per-user access control?" If yes, treat the memory store the same way.

### Multi-tenant memory isolation
**What.** In SaaS agent products, different tenants (customers) must have completely isolated memory stores. A retrieval query from tenant A must never return memories from tenant B.
**Use when.** Any multi-tenant agent product.
**Advantages.**
- Prevents data leakage between customers — this is a hard security requirement
**Tradeoffs.**
- Requires tenant-partitioned storage and retrieval; shared vector stores need careful filtering
**Staff signal.** Vector similarity search is particularly dangerous for multi-tenant isolation: if your vector store does not enforce tenant-level partitioning natively, a similarity query may return cross-tenant results that are then filtered too late (after being scored). Ensure partitioning happens at the query level, not as a post-filter.

### Cache vs memory distinction
**What.** Prompt caching (e.g., caching the system prompt prefix) is a cost optimization at the inference layer — it reduces token cost for repeated prefixes. It is not a memory system. Persistent memory is an application-layer concept about what information the agent retains across sessions.
**Use when.** Clarifying architecture: teams often confuse infrastructure-level caching with application-level memory.
**Advantages.**
- Correctly distinguishing these prevents architectural confusion
**Tradeoffs.**
- None — this is purely a conceptual clarity point
**Staff signal.** When someone says "we have memory because we use prompt caching," correct them. Prompt caching reduces cost; memory changes behavior. They operate at different layers and serve different purposes.

## State management patterns

### State machines for agent workflows
**What.** Model the agent's workflow as an explicit state machine: defined states (gathering_info, executing, reviewing, complete), defined transitions (gather→execute when all inputs are collected), and per-state tool sets and prompts. This contrasts with implicit state — where the agent's current "phase" is inferred from the conversation history.
**Use when.** Complex agent workflows with distinct phases.
**Advantages.**
- Explicit state is testable, auditable, and debuggable; you can inspect which state the agent is in at any time
- Per-state tool subsets reduce tool-selection errors
**Tradeoffs.**
- Requires upfront workflow modeling; less flexible than a fully autonomous agent
**Staff signal.** Explicit state machines are the practical middle ground between rigid pipelines and fully autonomous agents. You get the adaptability of LLM reasoning within each state, but the transitions are controlled by code. This is what most production agents actually look like.

### Concurrent session consistency
**What.** When the same user has multiple simultaneous sessions (e.g., two browser tabs), both sessions may read and write to the same user-scoped memory store. Without coordination, one session may overwrite another's changes, or read stale state.
**Use when.** Any multi-session agent product (which is most of them — users open multiple tabs).
**Advantages.**
- Addressing this prevents confusing user experiences (agent "forgets" something just written in another tab)
**Tradeoffs.**
- Full consistency adds coordination overhead; eventual consistency may cause brief inconsistencies
**Staff signal.** Eventual consistency is acceptable for most agent memory systems — memories are supplementary context, not transactional state. But if the agent manages task state (todo lists, order status), you need at least read-your-own-writes consistency to avoid confusing the user.

### Memory retrieval cost per turn
**What.** Every turn that triggers memory retrieval adds latency (embedding the query, searching the store, fetching results) and token cost (retrieved memories consume context). For most systems, this adds 100-500ms and a few hundred to a few thousand tokens per turn.
**Use when.** Optimizing agent response latency.
**Advantages.**
- Awareness of this cost lets you budget and optimize
**Tradeoffs.**
- Skipping retrieval to save latency means the agent has no cross-session memory — there is no free option
**Staff signal.** Not every turn needs memory retrieval. Implement retrieval triggers: only retrieve when the user's message contains signals that past context would help (references to previous interactions, preference-dependent decisions). This saves latency on turns that don't benefit from memory.

### Evaluating memory quality
**What.** Measuring whether the memory system is helping: does the agent recall the right information at the right time? Metrics: retrieval precision (fraction of retrieved memories that are relevant), retrieval recall (fraction of relevant memories that are retrieved), and task-level impact (does memory improve task completion rate or user satisfaction).
**Use when.** Any production memory system — you need to know if it's working.
**Advantages.**
- Quantitative evaluation prevents memory systems from degrading silently
**Tradeoffs.**
- Requires labeled data (which memories should have been retrieved for which queries), which is expensive to create
**Staff signal.** The most common failure mode of memory systems is retrieving irrelevant memories. This wastes context tokens and confuses the model. If you can only measure one thing, measure retrieval precision — how often do the retrieved memories actually get used in the model's response.

### Privacy and PII in memory stores
**What.** Memory stores accumulate PII (names, emails, preferences, conversation content). This data must be encrypted at rest and in transit, access-controlled per user/tenant, and deletable on request (GDPR, CCPA). Memory extraction may inadvertently capture sensitive information the user did not intend to persist.
**Use when.** Any production memory system — this is a compliance requirement, not an optimization.
**Advantages.**
- Compliance with privacy regulations; user trust
**Tradeoffs.**
- Encryption may limit certain query types (e.g., can't do similarity search on encrypted embeddings without specialized approaches)
- PII detection in unstructured memories is imperfect; some PII will slip through automated filters
**Staff signal.** Apply the principle of least persistence: only store what the agent demonstrably needs. Every stored memory is a liability. Design memory extraction to exclude PII by default and include it only when explicitly required by the use case. This is cheaper than retroactive PII scrubbing.

## Common interview traps

- **Treating context window as infinite.** Even models with 1M+ token windows degrade on recall for information in the middle. Context management is always necessary.
- **Conflating prompt caching with memory.** Caching is a cost optimization; memory is a behavior change. They solve different problems.
- **Ignoring memory retrieval precision.** Candidates discuss what to store but not how to retrieve effectively. Retrieving wrong memories is worse than no memory.
- **Forgetting GDPR/right-to-erasure.** Any memory system that stores user data must support complete deletion per user. Design for this upfront.
- **Assuming vector stores are sufficient.** Structured data (user preferences, account facts) is better served by relational stores with exact lookups. Vector stores are for fuzzy/semantic retrieval.
- **Not addressing unbounded growth.** Memory stores grow forever without active management (TTL, deduplication, pruning). This is an operational issue that surfaces months after launch.
- **Skipping memory scope isolation.** In multi-tenant systems, cross-tenant memory leakage is a security incident, not a bug.
- **Overlooking summarization quality.** Candidates say "summarize older context" without specifying what the summary must preserve. Generic summaries lose critical details.

## Drill questions

1. Your agent's context window is 128K tokens, but you observe quality degradation after ~30K. How do you design the context management strategy? What goes where?
2. A user says "I changed my email to X" in session 5. How does your memory system ensure sessions 6+ use the new email and never cite the old one?
3. Compare vector store vs relational store for storing user preferences. When does each win? Can you use both, and how?
4. Design a memory retrieval pipeline that balances relevance, recency, and importance. How do you weight these signals, and how do you evaluate whether the weighting is correct?
5. Your memory store has grown to 50,000 entries per user. Retrieval quality is declining. What operational steps do you take?
6. A GDPR deletion request arrives for a user. Walk through exactly what you delete, and how you ensure completeness — including memories that reference the user indirectly.
7. Your agent runs for 200 turns in a coding session. Design the hierarchical summarization strategy: what is verbatim, what is summarized, and at what granularity?
8. Two simultaneous sessions for the same user both update a memory. How do you handle the conflict? Does it matter if the memory is a preference vs a task state?
9. You suspect your memory system is hurting more than helping (retrieved memories confuse the model). How do you measure this and what do you change?
10. Design the checkpoint format for a multi-step agent that calls external APIs. What do you persist, how do you resume after a crash, and how do you handle a schema change between the crash and the resume?
