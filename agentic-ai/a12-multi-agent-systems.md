# A12. Multi-Agent Systems

A multi-agent system uses multiple LLM-powered agents — each with its own context window, tools, and instructions — to collaborate on a task. The core engineering insight is that this is a distributed system where every node is expensive, slow, non-deterministic, and unreliable. The default design should be a single agent with more tools; multi-agent architectures are justified only when specific decomposition criteria are met. Over-decomposition is the most common and most costly mistake in this space.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Single agent vs multi-agent | Default to one agent; decompose only with evidence | Starting any agent architecture design |
| Decomposition criteria | Conditions that justify splitting into multiple agents | Evaluating whether multi-agent is warranted |
| Context isolation | Strongest motivation for subagents | Agent's context window is the binding constraint |
| Orchestrator-worker topology | Central coordinator delegates to specialist workers | Well-defined subtasks with clear routing |
| Hierarchical topology | Manager-of-managers for complex task trees | Large-scale decomposition with layered authority |
| Peer-to-peer topology | Agents communicate directly without a coordinator | Exploratory collaboration — rare in production |
| Blackboard / shared state | Agents read/write a shared workspace | Iterative refinement by multiple specialists |
| Sequential pipelines | Chain of specialized agents in fixed order | Well-understood processing stages |
| Handoffs | Transferring control between agents | One agent's job ends and another's begins |
| Agent-as-tool vs true handoff | Whether the caller retains control or transfers it | Choosing interaction pattern between agents |
| Communication protocols | Structured messages between agents | Agents must exchange information reliably |
| Interoperability standards | Cross-system agent communication (A2A-style) | Agents from different teams or vendors must cooperate |
| Task allocation and routing | Directing work to the right agent | Multiple agents with different specializations |
| Conflict resolution | Handling disagreements between agents | Agents produce contradictory outputs |
| Error propagation | Failures cascading across agents | Designing fault tolerance |
| Cost multiplication | Each agent has its own context and loop cost | Budgeting multi-agent systems |
| Latency multiplication | Serial agent chains multiply end-to-end time | Latency-sensitive multi-agent workflows |
| Loop and deadlock risks | Agents calling each other indefinitely | Preventing runaway costs |
| Emergent behaviour | Unintended interactions between agents | Testing and safety |
| Debugging and tracing | Following a request across agents | Operating multi-agent in production |
| Evaluating multi-agent | Attributing failure to a specific agent | Improving multi-agent quality |
| Shared memory and state | Consistent state across agents | Agents need to build on each other's work |
| Permission boundaries | Least privilege per agent | Security in multi-agent topologies |
| Human oversight | Keeping humans in the loop across agents | Safety and compliance |
| Collapsing back to one agent | Reversing a multi-agent decision | Multi-agent overhead exceeds its value |

## When to Decompose (and When Not To)

### Single Agent vs Multi-Agent
**What.** A single agent with access to multiple tools handles a wide range of tasks within one context window. Multi-agent introduces multiple context windows, inter-agent communication, and coordination overhead. The single-agent approach is strictly better unless a specific decomposition criterion is met.
**Use when.** Starting any agent architecture design — begin with one agent and add more only when you have evidence the single agent cannot succeed.
**Advantages.**
- Single agent: simpler debugging, lower latency (no inter-agent communication), lower cost (one context window), easier evaluation, full context visibility
- Multi-agent: can exceed single-context-window limits, enables independent tool sets and permissions, allows parallelism on independent subtasks
**Tradeoffs.**
- Multi-agent adds coordination cost, communication overhead, failure modes, and debugging complexity at every level
- Teams are drawn to multi-agent architectures because they mirror human organizational structures, but LLMs do not benefit from org-chart decomposition
**Staff signal.** The question is never "should we use multiple agents?" — it is "what specific constraint makes a single agent fail?" If you cannot name the constraint (context window, tool conflicts, permission boundaries, parallelism), you do not need multi-agent. The burden of proof is on complexity.

### Decomposition Criteria
**What.** The specific conditions under which splitting into multiple agents produces a net benefit over a single agent: (1) distinct tool sets that conflict or confuse the agent, (2) distinct context needs that exceed a single context window, (3) distinct trust/permission boundaries, (4) parallelizable independent subtasks, (5) separate ownership/teams that need independent development and deployment cycles.
**Use when.** Evaluating a proposed multi-agent architecture to verify it is justified.
**Advantages.**
- Provides a checklist that prevents over-decomposition
- Each criterion corresponds to a real engineering benefit, not an aesthetic preference
**Tradeoffs.**
- Criteria overlap; some situations satisfy multiple criteria, making the decomposition clearly justified, while borderline cases require judgment
- Satisfying one criterion weakly is usually not sufficient — the coordination cost must be lower than the benefit
**Staff signal.** In interviews, when asked to design a multi-agent system, start by arguing for a single agent. Then identify which specific criterion forces decomposition. This demonstrates that you understand the cost of complexity and will not add agents for organizational aesthetics.

### Context Isolation
**What.** Each agent operates within its own context window. When a task requires processing more information than fits in one context window, or when unrelated context from one subtask pollutes another subtask's reasoning, splitting into agents with separate contexts directly addresses the problem.
**Use when.** A single agent's context window is overwhelmed by the breadth of information needed, or irrelevant context degrades reasoning quality on specific subtasks.
**Advantages.**
- Each agent sees only the context relevant to its subtask, improving reasoning quality
- Enables processing total information that exceeds any single model's context limit
**Tradeoffs.**
- Information lost at the boundary between agents must be explicitly communicated — the receiving agent does not know what it does not know
- Context isolation creates a "telephone game" risk where nuance is lost in handoff summaries
**Staff signal.** Context isolation is the strongest genuine motivation for multi-agent because it addresses a hard physical limit (context window size) rather than a soft organizational preference. When justifying multi-agent, lead with context isolation if it applies.

## Topologies

### Orchestrator-Worker Topology
**What.** A central orchestrator agent receives the user request, decomposes it into subtasks, delegates each to a specialist worker agent, collects results, and synthesizes a response. The orchestrator owns the conversation state and decision-making.
**Use when.** Subtasks are well-defined, the routing logic is clear, and a central coordinator can maintain coherent overall reasoning.
**Advantages.**
- Clear control flow; the orchestrator is a single point of observability and debugging
- Workers can be simple and focused, with narrow tool sets and instructions
- Orchestrator can retry or reassign failed subtasks
**Tradeoffs.**
- The orchestrator is a bottleneck and single point of failure; its context window must hold the task decomposition and all worker results
- Orchestrator quality determines overall quality — a poor decomposition leads to poor results regardless of worker quality
- Latency equals orchestrator processing plus the slowest worker (serial) or orchestrator plus worker (parallel)
**Staff signal.** The orchestrator-worker pattern mirrors the coordinator pattern in distributed systems. The orchestrator must be your best model (or at least the most reliable at planning and routing), not the cheapest. Skimping on the orchestrator to save cost is a false economy.

### Hierarchical / Manager-of-Managers Topology
**What.** An extension of orchestrator-worker where the orchestrator delegates to sub-orchestrators, each managing their own workers. Creates a tree of delegation suitable for complex tasks with multiple levels of decomposition.
**Use when.** The task is genuinely too complex for a single orchestrator to decompose in one step — rare in practice.
**Advantages.**
- Scales to complex tasks that require decomposition beyond what one context window can plan
- Each sub-tree can be developed and evaluated independently
**Tradeoffs.**
- Latency grows with tree depth — each level adds at least one full LLM call's latency
- Error amplification: mistakes at higher levels cascade to all downstream agents
- Debugging requires tracing through multiple levels of delegation
**Staff signal.** Hierarchical multi-agent is almost never necessary in current production systems. If you find yourself designing more than two levels of delegation, reconsider whether the task actually requires this complexity. Most "hierarchical" designs can be flattened into a single orchestrator with well-designed workers.

### Peer-to-Peer / Network Topology
**What.** Agents communicate directly with each other without a central coordinator. Any agent can invoke any other agent, forming a graph of interactions.
**Use when.** Genuinely exploratory collaboration where no single agent has authority — extremely rare in production.
**Advantages.**
- Maximum flexibility; agents can dynamically choose collaborators
- No single-point-of-failure coordinator
**Tradeoffs.**
- Extremely hard to debug — no single trace tells the full story
- Conversation loops and deadlocks are difficult to prevent without global supervision
- Non-deterministic execution order makes reproducibility nearly impossible
**Staff signal.** Peer-to-peer multi-agent is a research architecture, not a production architecture. If you encounter it in a design discussion, argue for introducing a coordinator. The debugging and observability cost of peer-to-peer in production outweighs any flexibility benefit.

### Blackboard / Shared-State Coordination
**What.** Agents communicate by reading from and writing to a shared workspace (blackboard) rather than sending messages to each other. Each agent monitors the blackboard for items it can contribute to.
**Use when.** Multiple specialists iteratively refine a shared artifact (e.g., a document, a plan, or a codebase).
**Advantages.**
- Decouples agents temporally — agents do not need to be invoked in a fixed order
- The blackboard provides a natural audit trail of contributions
**Tradeoffs.**
- Concurrent writes require conflict resolution (last-writer-wins is simplest but lossy)
- State management becomes the critical infrastructure; the blackboard must be durable, consistent, and observable
- Agents may overwrite each other's work without awareness
**Staff signal.** Blackboard coordination works well when agents contribute to different sections of a shared artifact (e.g., one agent writes code, another writes tests, a third reviews). It fails when agents modify the same section — you need a merge strategy, and LLMs are poor at three-way merges.

### Sequential Pipelines
**What.** A fixed chain of agents where each agent's output is the next agent's input — like a Unix pipeline for LLM processing stages.
**Use when.** The task decomposes into well-understood, ordered stages (e.g., extract → validate → transform → summarize).
**Advantages.**
- Simple, predictable control flow; easy to debug and evaluate per stage
- Each stage can use a different model (cheap model for extraction, expensive model for reasoning)
**Tradeoffs.**
- Rigid — cannot skip stages or reorder based on input; poor fit for tasks that need dynamic routing
- Latency is the sum of all stages; no parallelism
- Each stage is a potential quality bottleneck — one poor stage degrades all downstream stages
**Staff signal.** Sequential pipelines are the most underrated multi-agent pattern. They are simple, debuggable, and often sufficient. Before reaching for an orchestrator, check whether a fixed pipeline with 2–3 stages solves the problem. Pipelines compose better than orchestrators because each stage has a clear contract.

## Agent Interactions

### Handoffs
**What.** Transferring control from one agent to another, including the context the receiving agent needs to continue the task. The central challenge is the context-transfer problem: what does the receiving agent need to know, and what gets lost?
**Use when.** One agent's portion of the task is complete and a different agent (different tools, different instructions) must continue.
**Advantages.**
- Enables specialization without requiring one agent to master all tools
- Clean handoff points create natural evaluation boundaries
**Tradeoffs.**
- Context transfer is lossy — the handoff summary may omit information the receiving agent later needs
- The receiving agent cannot ask the sending agent for clarification (unless you build that mechanism)
- Handoff design is where most multi-agent systems fail in practice
**Staff signal.** The handoff summary is the most critical piece of multi-agent design. Invest in structured handoff messages with explicit sections (task, completed work, remaining work, constraints, relevant data). Freeform handoff summaries degrade as task complexity grows.

### Agent-as-Tool vs True Handoff
**What.** In agent-as-tool, agent A calls agent B like a function — A retains control and uses B's output as one input to its reasoning. In a true handoff, agent A transfers control entirely to agent B, and A's job is done.
**Use when.** Choosing between these two interaction patterns for a specific agent-to-agent relationship.
**Advantages.**
- Agent-as-tool: caller retains context and can integrate multiple tool-agent results; simpler to debug because the caller's trace is continuous
- True handoff: reduces context load on the originating agent; enables routing to the best agent for the remainder of the task
**Tradeoffs.**
- Agent-as-tool: caller's context grows with each sub-agent result; deep nesting of agent-as-tool calls can be very expensive
- True handoff: no single agent has full visibility; state must be explicitly transferred
**Staff signal.** Default to agent-as-tool for short, bounded subtasks (the calling agent can consume the result in its context). Use true handoff only when the subtask is large enough that the calling agent's context cannot or should not hold the full interaction.

### Communication Protocols and Message Schemas
**What.** Defining structured message formats for inter-agent communication rather than relying on freeform natural language. Messages have typed fields (task type, input data, constraints, expected output format) that reduce ambiguity.
**Use when.** Building any multi-agent system that must be reliable in production.
**Advantages.**
- Structured messages reduce misinterpretation — an agent cannot ignore a field it does not understand
- Enables validation, logging, and monitoring of inter-agent communication
- Makes inter-agent contracts testable
**Tradeoffs.**
- Schema design is an upfront investment; over-specification makes the system rigid
- Agents may still misinterpret field contents despite structural compliance
**Staff signal.** Treat inter-agent messages like API contracts. Define a schema, validate on send and receive, version the schema, and log every message. Free-text inter-agent communication in production is the multi-agent equivalent of untyped APIs — it works in demos and breaks under load.

### Agent-to-Agent Interoperability Standards
**What.** Emerging protocols (e.g., A2A-style specifications) for cross-system agent communication — enabling agents built by different teams or vendors to discover and invoke each other with standardized capability descriptions and message formats.
**Use when.** Agents from different organizations or platforms must cooperate, or you are designing for an ecosystem of pluggable agents.
**Advantages.**
- Standardized discovery and invocation reduce integration cost for each new agent pair
- Enables marketplace/ecosystem dynamics where third-party agents can be composed
**Tradeoffs.**
- Trust is the fundamental open question: how do you verify that an external agent is safe, reliable, and not adversarial?
- Standards are immature and evolving rapidly; building on them incurs early-adopter risk
- Interoperability adds latency and failure modes at every cross-system boundary
**Staff signal.** Interoperability standards are important but premature for most teams. The trust model is unsolved — invoking an external agent is like calling an untrusted API that can also reason about your data. Until trust and capability verification are mature, prefer internal agents with known behaviour over external agent ecosystems.

### Task Allocation and Routing
**What.** The mechanism by which incoming tasks or subtasks are directed to the appropriate agent based on capability matching, load, or specialization.
**Use when.** Multiple agents exist with different specializations and tasks must be routed to the best one.
**Advantages.**
- Classifier-based routing (LLM or traditional ML) enables dynamic task distribution
- Enables scaling by adding specialized agents without changing the routing logic
**Tradeoffs.**
- Router accuracy is critical — misrouted tasks fail or produce poor results
- Router is itself a model call that adds latency and cost; must be fast and cheap
**Staff signal.** The router is the most important component in a multi-agent system because every downstream error can be traced to either a routing mistake or an agent capability gap. Evaluate the router independently: measure routing accuracy on a labeled dataset before trusting it to orchestrate production traffic.

## Failure and Cost

### Conflict Resolution When Agents Disagree
**What.** When multiple agents produce contradictory outputs for the same question, a resolution mechanism is needed: voting/ensembling, confidence-weighted selection, or escalation to a judge agent.
**Use when.** You use multiple agents for the same task (redundancy, diversity of perspective) or agents' outputs must be reconciled.
**Advantages.**
- Voting/ensembling can improve reliability when individual agents are unreliable but uncorrelated in their errors
- A judge agent can apply structured criteria to choose the best output
**Tradeoffs.**
- Voting multiplies cost by the number of voters; only justified when reliability improvement outweighs cost
- Agents' errors are often correlated (same model, similar prompts), reducing the value of ensembling
**Staff signal.** Conflict resolution via voting is expensive and only works if agent errors are uncorrelated. Using the same model with different prompts gives weakly correlated errors — modest benefit. Using different model families gives more decorrelation — higher benefit but also higher operational complexity. Measure the reliability improvement before committing to the cost.

### Error Propagation and Partial Failure
**What.** When one agent in a multi-agent system fails (timeout, hallucination, tool error), the failure can propagate to dependent agents. Partial failure — where some agents succeed and others fail — requires decisions about retry, fallback, and graceful degradation.
**Use when.** Designing fault tolerance for any multi-agent system.
**Advantages.**
- Explicit error-handling contracts between agents (what to do on failure) prevent silent propagation of bad outputs
- Circuit-breaker patterns from distributed systems apply: stop sending work to a failing agent
**Tradeoffs.**
- Retry logic must be bounded — retrying an LLM call that hallucinated may produce the same hallucination
- Partial failure is harder to handle than total failure; deciding which partial results to keep requires judgment
**Staff signal.** The most dangerous failure in multi-agent is not a crash — it is a confident hallucination that propagates unchecked through the agent chain. Each agent should validate its inputs (from the previous agent) as well as its outputs. Trust no upstream agent unconditionally.

### Cost Multiplication
**What.** Each agent in a multi-agent system has its own context window and reasoning loop, meaning total token cost is the sum of all agents' token consumption, not the cost of a single agent's context. Multi-step orchestration multiplies cost further.
**Use when.** Budgeting or justifying a multi-agent architecture.
**Advantages.**
- Explicit cost modeling prevents sticker shock at production scale
**Tradeoffs.**
- A 3-agent system where each agent does a 5-step loop with 8k-token context costs roughly 15× a single-call system (3 agents × 5 steps × 8k tokens per step vs 1 × 1 × 8k)
- Context transferred between agents is processed redundantly — both the sender and receiver pay tokens for it
**Staff signal.** Before proposing a multi-agent design, compute the multiplicative cost overhead vs a single-agent alternative. Present both numbers. If the multi-agent design costs 10× more, the quality improvement must be substantial and measurable to justify it. "Cleaner architecture" is not a justification for 10× cost.

### Latency Multiplication
**What.** Serial agent chains multiply end-to-end latency. Each agent in a serial dependency adds at least one full LLM call's latency (typically 1–10 seconds depending on context length and model size). Even with parallelism, the critical path determines total latency.
**Use when.** Designing latency-sensitive multi-agent systems.
**Advantages.**
- Explicit critical-path analysis reveals which agent-to-agent dependencies can be parallelized
**Tradeoffs.**
- A 4-agent serial chain with 3-second average per agent takes 12+ seconds end-to-end — often unacceptable for interactive use
- Parallelization helps only for independent subtasks; serial dependencies cannot be parallelized
**Staff signal.** Draw the dependency graph of your multi-agent system and identify the critical path. The sum of LLM call latencies on the critical path is your latency floor — no optimization can go below it without removing agents from the path. If the floor exceeds your latency budget, you have too many serial agents.

### Loop and Deadlock Risks
**What.** Agents that can call each other may enter infinite loops (A calls B, B calls A) or deadlocks (A waits for B's output, B waits for A's). These are the multi-agent equivalents of infinite recursion and circular dependencies.
**Use when.** Designing inter-agent call graphs — especially in peer-to-peer or cyclic topologies.
**Advantages.**
- Global step budgets (maximum total LLM calls across all agents per task) prevent unbounded cost
- Acyclic agent call graphs (enforced by design) eliminate loops structurally
**Tradeoffs.**
- Step budgets are blunt instruments — they may terminate a valid long-running task prematurely
- Detecting cycles in runtime is expensive; preventing them by design is cheaper
**Staff signal.** Enforce a global step budget on every multi-agent system. This is non-negotiable. Without it, a single user request can trigger unbounded LLM calls across agents, consuming your entire inference budget. Set the budget conservatively and raise it with evidence, not optimism.

### Emergent and Unintended Behaviour
**What.** When multiple non-deterministic agents interact, their combined behaviour can produce outcomes that no single agent was designed to produce and that were not anticipated by the system designer. This is fundamentally harder to test than single-agent behaviour.
**Use when.** Assessing safety and reliability of multi-agent systems.
**Advantages.**
- Awareness drives investment in end-to-end testing on realistic scenarios, not just unit testing of individual agents
**Tradeoffs.**
- The combinatorial space of multi-agent interactions is too large to test exhaustively
- Emergent behaviour may appear only at scale or under specific input distributions
**Staff signal.** Emergent behaviour is why multi-agent systems require end-to-end integration tests, not just per-agent unit tests. A system where each agent scores 95% individually can easily score 70% end-to-end due to compounding errors and unintended interactions.

## Operations

### Debugging and Tracing Multi-Agent Runs
**What.** Following a single user request as it flows through multiple agents, correlating LLM calls, tool invocations, handoffs, and outputs across the full execution graph.
**Use when.** Operating any multi-agent system in production.
**Advantages.**
- Distributed tracing (correlation IDs propagated across agents) enables root-cause analysis
- Structured logging of inter-agent messages creates an audit trail
**Tradeoffs.**
- Tooling for multi-agent tracing is immature compared to microservices tracing
- Non-determinism means the same input may produce different traces on re-execution
**Staff signal.** Apply distributed-systems observability to multi-agent: correlation IDs, structured logs, span trees, and latency waterfall views. The agent call graph is isomorphic to a microservices call graph — use the same tools and patterns. If you cannot reconstruct the full execution path from a request ID, you cannot debug production issues.

### Evaluating Multi-Agent Systems
**What.** Measuring end-to-end quality and attributing failures to specific agents in the chain. Requires both per-agent evaluation (did this agent do its job?) and end-to-end evaluation (did the system produce the right final answer?).
**Use when.** Improving multi-agent quality after initial deployment.
**Advantages.**
- Per-agent evaluation isolates which component is the bottleneck; end-to-end evaluation catches interaction failures
- Attribution enables targeted improvement: fix the worst agent or the weakest handoff
**Tradeoffs.**
- Failure attribution is difficult when agents' outputs are consumed as inputs by other agents — an upstream error may surface as a downstream failure
- Requires maintaining eval sets at both per-agent and end-to-end levels
**Staff signal.** Build two evaluation layers: per-agent (each agent's input/output quality on isolated examples) and end-to-end (system-level quality on realistic scenarios). When end-to-end quality drops but all per-agent evals pass, the problem is in the handoffs or orchestration — the integration layer.

### Shared Memory and State Consistency
**What.** When agents need to build on each other's work (e.g., one agent writes code, another writes tests for it), they need access to shared state. Consistency guarantees determine whether agents see each other's updates reliably.
**Use when.** Agents must coordinate on shared artifacts or data.
**Advantages.**
- Shared state (database, file system, memory store) avoids transmitting large artifacts through context windows
- Reduces context token cost — agents reference shared state instead of embedding it
**Tradeoffs.**
- Concurrent modifications require conflict resolution; LLMs cannot perform three-way merges reliably
- Stale reads (one agent acts on outdated state) cause subtle, hard-to-diagnose failures
**Staff signal.** Keep shared state as simple as possible — append-only logs or section-based ownership (each agent owns distinct sections) are far more reliable than concurrent writes to the same data. If you need concurrent writes, use a deterministic merge strategy, not an LLM-based one.

### Permission Boundaries Per Agent
**What.** Applying least-privilege principles to multi-agent systems: each agent should have access only to the tools, data, and capabilities it needs for its specific role.
**Use when.** Designing any multi-agent system with access to sensitive tools or data.
**Advantages.**
- Limits blast radius when an agent hallucinates a dangerous tool call or is manipulated by adversarial input
- Satisfies compliance requirements for data access segregation
**Tradeoffs.**
- Permission management adds complexity — each agent's tool set must be configured and maintained
- Overly restrictive permissions cause agents to fail on legitimate tasks
**Staff signal.** Multi-agent is one of the best reasons *for* agent decomposition: it lets you give the "read financial data" agent read-only database access and the "send email" agent SMTP access, without either having the other's capabilities. If all your agents have the same tool set and permissions, you have a multi-agent system without the security benefit that justifies it.

### Human Oversight in Multi-Agent Systems
**What.** Maintaining human-in-the-loop review and approval points as tasks flow through multiple agents. More critical in multi-agent than single-agent because the execution is more opaque and higher-risk actions may be distributed across agents.
**Use when.** Multi-agent systems perform consequential actions (financial transactions, external communications, data modifications).
**Advantages.**
- Checkpoint-based approval (human approves before high-risk stages) catches errors before they propagate
- Audit trail of human approvals satisfies compliance requirements
**Tradeoffs.**
- Human checkpoints add latency and break the flow of autonomous operation
- Too many checkpoints negate the value of automation; too few allow dangerous cascading errors
**Staff signal.** Place human approval gates at trust boundaries, not at every agent transition. Identify the specific actions that are irreversible or high-impact (sending external messages, writing to production databases, committing code) and require approval only there. Everything else can be reviewed post-hoc via audit logs.

### When to Collapse Back to One Agent
**What.** The conditions under which a multi-agent architecture should be simplified back to a single agent or a deterministic workflow: coordination cost exceeds the value of decomposition, latency is unacceptable, cost is unjustifiable, debugging is unmanageable, or models have improved enough that one agent can handle the full task.
**Use when.** Periodically re-evaluating a multi-agent design, or when operational costs exceed expectations.
**Advantages.**
- Dramatic simplification: fewer models to manage, simpler debugging, lower cost, lower latency
- Model capability improvements may eliminate the original reason for decomposition
**Tradeoffs.**
- Political resistance — teams that own individual agents resist consolidation
- Consolidation may require a larger model or longer context, which has its own costs
**Staff signal.** Schedule a quarterly review of multi-agent architectures with a standing question: "can we remove an agent?" As models improve and context windows grow, the decomposition that was necessary 6 months ago may now be overhead. The best multi-agent architecture is the one with the fewest agents that still meets quality, latency, and cost targets.

## Common interview traps

- **Starting with multi-agent.** Candidates propose elaborate multi-agent architectures before demonstrating that a single agent is insufficient. Always start with one agent and justify decomposition.
- **Confusing org-chart decomposition with technical decomposition.** Splitting agents by team boundary ("the commerce agent, the support agent, the analytics agent") is an organizational choice, not a technical one. Split by context/tool/permission boundaries.
- **Ignoring cost multiplication.** Candidates describe multi-agent benefits without computing the cost overhead. A 5-agent system does not cost 5× a single agent — it costs 5× per step across potentially multiple steps per agent.
- **No global step budget.** Any multi-agent system without a hard cap on total LLM calls per task is an unbounded-cost system. This is always wrong.
- **Underestimating handoff loss.** Candidates assume agents can "hand off" seamlessly, but the receiving agent only knows what the handoff message contains. Critical context is routinely lost.
- **Peer-to-peer in production.** Peer-to-peer multi-agent is nearly impossible to debug and observe. It is a research pattern, not a production pattern.
- **Treating agents as microservices.** Agents are not stateless, deterministic services. They are expensive, slow, non-deterministic, and unreliable. Apply distributed-systems patterns but adjust expectations.
- **No per-agent evaluation.** End-to-end testing without per-agent evaluation means you cannot localize failures. You need both layers.

## Drill questions

1. A colleague proposes a 5-agent system for a task currently handled by one agent with a long prompt. How do you evaluate whether the decomposition is justified?
2. Your multi-agent system costs 10× more than a single-agent alternative. When is this justified, and how do you decide?
3. Agent B receives a handoff from Agent A and produces poor results. How do you determine whether the problem is A's handoff summary or B's reasoning?
4. How do you prevent two agents from entering an infinite loop of mutual invocation? Describe both design-time and runtime approaches.
5. Your orchestrator-worker system has a latency of 15 seconds. The orchestrator takes 3 seconds, and it calls 3 workers sequentially at 4 seconds each. How do you reduce latency without reducing quality?
6. When is blackboard/shared-state coordination preferable to message-passing between agents?
7. Describe how you would implement distributed tracing for a multi-agent system. What would you log at each agent boundary?
8. You notice that your multi-agent system occasionally produces outputs that no individual agent was designed to produce. How do you diagnose and mitigate this?
9. What specific conditions would lead you to collapse a multi-agent system back into a single agent?
10. How do you apply least-privilege principles to a multi-agent system with access to a database, an email API, and a code execution sandbox?
11. Your multi-agent system passes end-to-end evaluation 85% of the time, but each individual agent passes its per-agent evaluation 95% of the time. What explains the gap, and how do you close it?
12. When would you use agent-as-tool vs a true handoff? Give an example of each and explain the tradeoff.
