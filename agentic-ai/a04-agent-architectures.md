# A4. Agent Architectures & Orchestration

An agent is a control loop where an LLM selects the next action, observes the result, and decides whether to continue or stop. The central engineering question is not "can we build an agent?" but "how much control-flow authority should we delegate to the model versus hard-code?" Every increment of model autonomy buys flexibility and costs you predictability, testability, cost control, and debuggability. This section maps the spectrum from deterministic pipelines to fully autonomous agents, and the orchestration patterns that compose them.

## Quick-reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Agent vs chatbot vs pipeline | Defines autonomy boundaries | Deciding whether you need an agent at all |
| Workflow vs agent axis | Deterministic code vs model-decided control | The first architectural decision for any LLM feature |
| When NOT to build an agent | Cost/reliability gate | Justifying complexity to stakeholders |
| Core agent loop | Observe → reason → act → observe | Implementing any agent from scratch |
| ReAct-style loops | Interleaved reasoning and action | Single-agent tool-use tasks |
| Plan-then-execute vs interleaved | Upfront plan vs step-by-step | Tasks with known structure vs exploratory tasks |
| Reflection / self-critique | Output quality via self-evaluation | High-stakes generation where first-pass errors are costly |
| Tree/graph search | Branching exploration of action space | Tasks with verifiable outcomes and tolerable latency |
| Prompt chaining | Sequential step decomposition | Multi-step tasks with known shape |
| Routing / dispatch | Classify-then-delegate | Heterogeneous request types hitting one endpoint |
| Parallelization | Sectioning and voting | Independent subtasks or reliability via redundancy |
| Orchestrator-worker | Dynamic task decomposition | Complex tasks whose subtasks are only known at runtime |
| Supervisor / hierarchical | Manager agents above worker agents | Multi-domain tasks needing coordination |
| Agent-as-tool | Agent callable by another agent | Encapsulating complex capability behind a tool interface |
| Handoff / delegation | Transfer control and context between agents | Specialized agents needing to cooperate |
| Termination conditions | When and why to stop | Every agent — the most under-designed aspect |
| Stuck-loop detection | Breaking degenerate repetition | Production agents left running without human oversight |
| Human-in-the-loop | Approval, escalation, confidence gates | Mutating actions, high-cost decisions, low-confidence outputs |
| Interruptibility / pause-resume | Long-running agent lifecycle | User-facing agents, overnight batch agents |
| Statefulness / checkpointing | Durable execution for agents | Multi-step runs that must survive crashes |
| Idempotency of actions | Safe retry after failure | Any agent that writes to external systems |
| Determinism boundaries | Side-effect isolation | Testing and safe replay |
| Cost/latency budgeting | Step-level resource caps | Production cost governance |
| Streaming intermediate progress | UX for long-running agents | User-facing agents where silence kills trust |
| Framework vs build-your-own | Build/buy decision | Starting a new agent project |

## Defining autonomy

### Agent vs chatbot vs pipeline
**What.** A pipeline is a fixed DAG of steps — code decides every branch. A chatbot is a single-turn or multi-turn LLM that responds but does not act on the world. An agent is an LLM in a loop that selects actions, observes results, and decides the next step — it has autonomy over control flow.
**Use when.** You need to distinguish marketing from architecture. Many "agents" in production are actually pipelines with one LLM step; this is often the right choice.
**Advantages.**
- Clear vocabulary prevents over-engineering (calling a pipeline an "agent" invites unnecessary complexity)
- Forces you to identify which component actually needs autonomy
**Tradeoffs.**
- The boundaries blur: a pipeline with an LLM routing step has partial autonomy — purity is less useful than recognizing the continuum
**Staff signal.** The highest-leverage question in agent design is "does the model need to decide the control flow, or can I hard-code it?" If you can hard-code it, you should — it will be cheaper, faster, and testable.

### Workflow vs agent: the design axis
**What.** The single most important architectural axis. A *workflow* is code-defined control flow that may invoke LLMs at specific points — the developer decides the sequence. An *agent* is model-defined control flow where the LLM decides what to do next. Most production systems are a mix: workflow shells with agent sub-loops for specific steps.
**Use when.** Making the very first design decision. Decision rule: if the set of steps and their order is knowable at design time, use a workflow. If the task requires dynamic, context-dependent action selection across a variable number of steps, consider an agent loop.
**Advantages.**
- Workflows: predictable latency, deterministic testing, auditable, cheap
- Agents: handle novel situations, adapt to unexpected intermediate results
**Tradeoffs.**
- Agents multiply LLM calls (cost, latency), are harder to test, and their failure modes are emergent rather than designed
- Over-indexing on workflows makes the system brittle to requirement changes
**Staff signal.** Start with a workflow. Upgrade individual steps to agent loops only when you prove the step needs dynamic action selection. A workflow with one agent-loop step is almost always better than a fully autonomous agent.

### When NOT to build an agent
**What.** The strongest staff-level answer to any agent design question is knowing when an agent is the wrong tool. Deterministic workflows are cheaper per execution, faster (one LLM call vs many), testable with standard unit/integration tests, and produce auditable traces.
**Use when.** A stakeholder says "let's build an agent" and the task has a fixed, known structure.
**Advantages.**
- You ship faster, spend less on inference, and sleep better
**Tradeoffs.**
- You may need to refactor to an agent later if requirements become genuinely dynamic
**Staff signal.** The failure mode of unnecessary agents is not just cost — it is that you cannot write a meaningful test suite for emergent multi-step behavior, which means production failures are discovered by users.

## The core loop and reasoning patterns

### Core agent loop
**What.** Observe → reason → act → observe. The agent receives context (observation), the LLM reasons about next steps, emits an action (tool call or response), the action's result is appended to context, and the loop repeats. An iteration budget caps total steps.
**Use when.** Implementing any agent runtime. This loop is the irreducible primitive.
**Advantages.**
- Simple to implement; the entire complexity lives in the prompt and tool set
**Tradeoffs.**
- Each iteration is a full LLM round-trip (latency, cost). Context grows every step (token cost, potential overflow)
**Staff signal.** The iteration budget is not optional — it is your most important safety control. Without it, a confused model will burn tokens forever. Set it lower than you think (start with 5-10 steps), then raise based on observed production distributions.

### ReAct-style loops
**What.** A specific prompt pattern for the core loop: the model is asked to emit a Thought (reasoning), then an Action (tool call), then receives an Observation (tool result). This interleaving of explicit reasoning with action improves the model's ability to use tools correctly by forcing chain-of-thought before each call.
**Use when.** Single-agent tool-use tasks where you want inspectable reasoning traces.
**Advantages.**
- Thought traces provide natural observability and debuggability
- Empirically improves tool-use accuracy over action-only prompting
**Tradeoffs.**
- Thought tokens are expensive; they add ~30-50% overhead to context per step
- Modern function-calling APIs internalize some of this; explicit ReAct formatting may be redundant depending on the model
**Staff signal.** In production, log the thoughts but consider not streaming them to the user — they often contain confused reasoning that erodes trust, even when the final action is correct.

### Plan-then-execute vs interleaved planning
**What.** Plan-then-execute: the model first generates a full plan (list of steps), then a separate execution loop carries them out. Interleaved: the model plans and executes one step at a time, replanning implicitly with each iteration. Replanning triggers: unexpected error, new information that invalidates the plan, step that returns results requiring a different approach.
**Use when.** Plan-then-execute suits tasks with well-understood structure (e.g., data pipeline construction). Interleaved suits exploratory tasks (e.g., debugging, research).
**Advantages.**
- Plans are auditable and can be shown to users for approval before execution
- Interleaved adapts to surprise without wasting effort on obsolete plan steps
**Tradeoffs.**
- Plans go stale — the model may not know what tools return until it calls them, making upfront planning speculative
- Replanning adds LLM calls; replan-every-step converges to the interleaved pattern anyway
**Staff signal.** Plan-then-execute is valuable primarily for the human-approval step it enables. If you don't need user sign-off on the plan, interleaved planning is usually superior because it eliminates wasted plan steps.

### Reflection / self-critique loops
**What.** After generating output, a second LLM call (or the same model in a new turn) evaluates the output against criteria and suggests improvements. The evaluator-optimizer pattern: one call generates, another evaluates, the generator revises. This can iterate multiple times.
**Use when.** High-stakes generation (code, legal text, complex analysis) where first-pass errors are expensive and criteria can be articulated in a prompt.
**Advantages.**
- Catches errors the generator missed; especially effective for constraint satisfaction (format, style, factual checks)
**Tradeoffs.**
- Each reflection cycle is a full LLM call. Diminishing returns set in fast — typically the first reflection captures 70-80% of fixable errors. Beyond 2-3 cycles, you're burning tokens for marginal gains.
**Staff signal.** The cost of reflection scales linearly but the quality improvement is logarithmic. Instrument the quality delta per cycle and set a hard cap. In production, one reflection pass is the sweet spot for most applications.

### Tree/graph search over actions
**What.** Instead of a single linear chain, the agent explores multiple possible action paths (branching), potentially evaluating or scoring each path. Breadth-first explores many options shallowly; depth-first explores one path deeply before backtracking.
**Use when.** The task has a verifiable success criterion (e.g., code that must pass tests, math with checkable answers) and you can afford the cost.
**Advantages.**
- Can find solutions that linear chains miss, especially for combinatorial problems
**Tradeoffs.**
- Cost explosion: branching factor × depth × cost-per-call. A 3-wide, 5-deep tree is 243 LLM calls. Latency grows proportionally unless parallelized, which multiplies cost further.
**Staff signal.** Tree search is almost never used in user-facing production agents due to cost and latency. It appears in offline code generation and research. If you reach for tree search, ask whether a better prompt or tool set would eliminate the need.

## Composition patterns

### Prompt chaining
**What.** Sequential decomposition: break a complex task into a fixed sequence of LLM calls, where each call's output feeds the next. This is a workflow pattern — the developer defines the sequence.
**Use when.** A task has a known multi-step shape (extract → transform → validate → format). Each step is simple enough for a single LLM call.
**Advantages.**
- Each step can have its own prompt, model, and validation; easy to test and debug in isolation
- Latency is predictable: sum of step latencies
**Tradeoffs.**
- Rigid: cannot adapt to unexpected intermediate results without adding conditional logic in code
- Error propagation: a mistake in step 2 is baked into steps 3-N unless you add validation gates
**Staff signal.** Add a programmatic validation gate between steps (schema check, assertion, guardrail). This catches errors early and is far cheaper than discovering them at the end.

### Routing / dispatch
**What.** A classifier (LLM or traditional ML) examines the input and routes it to one of several specialized handlers — each handler can be a prompt, a chain, or an agent. This is a code-controlled fan-out.
**Use when.** A single endpoint receives heterogeneous request types (customer support with billing/technical/account categories). Each category benefits from a specialized prompt and tool set.
**Advantages.**
- Each handler is optimized for its category; simpler prompts, fewer tools per handler, better accuracy
- Can route low-complexity requests to cheaper/faster models
**Tradeoffs.**
- Misrouting is a single point of failure: a misclassified request goes to the wrong handler. Must monitor classification accuracy.
**Staff signal.** The router's latency is on the critical path of every request. Use the cheapest model that achieves acceptable routing accuracy (often a fine-tuned small model outperforms a large one at classification).

### Parallelization: sectioning and voting
**What.** Sectioning: split independent subtasks and run them in parallel (e.g., analyze three documents simultaneously). Voting/ensembling: run the same task N times and take the majority or best answer.
**Use when.** Sectioning: subtasks are genuinely independent (no data dependencies). Voting: the task has a verifiable answer and you need higher reliability than a single call provides.
**Advantages.**
- Sectioning reduces wall-clock latency to the slowest subtask (vs sum of all)
- Voting improves reliability for ~Nx cost
**Tradeoffs.**
- Sectioning requires merging results — the merge step can be a complex LLM call itself
- Voting multiplies cost; diminishing reliability gains beyond 3-5 votes for most tasks
**Staff signal.** Voting is most cost-effective when the per-call cost is low and the cost of a wrong answer is high. For expensive models, one call plus one reflection pass typically beats three-way voting.

### Orchestrator-worker
**What.** An orchestrator agent dynamically decomposes a task into subtasks, dispatches them to worker agents (or LLM calls), and synthesizes the results. Unlike prompt chaining, the subtasks are determined at runtime by the orchestrator, not at design time.
**Use when.** Complex tasks where the decomposition depends on the input — the developer cannot enumerate subtasks in advance.
**Advantages.**
- Flexible: adapts decomposition to each input
- Workers can run in parallel if independent
**Tradeoffs.**
- The orchestrator is a single point of failure; if it decomposes poorly, all workers produce wrong results
- Debugging requires tracing through the orchestrator's decisions and each worker's execution
**Staff signal.** Keep worker interfaces uniform (same input/output schema). This lets you test workers independently and swap implementations without changing the orchestrator.

### Supervisor / hierarchical agents
**What.** A supervisor agent manages multiple worker agents, routing tasks, collecting results, and deciding when the overall goal is met. In hierarchical setups, supervisors can manage other supervisors, forming a tree.
**Use when.** Multi-domain tasks where no single agent has the tools or context for the full job (e.g., a research agent coordinating a web-search agent, a code agent, and a writing agent).
**Advantages.**
- Separation of concerns: each agent has a focused tool set and prompt
- Context stays manageable per agent (not one giant context with all tools)
**Tradeoffs.**
- Coordination overhead: every delegation is an LLM call. Deep hierarchies multiply latency and cost.
- Information loss at handoff boundaries — the supervisor summarizes, losing detail
**Staff signal.** Keep hierarchies shallow (2 levels max in practice). Each level adds a full LLM round-trip and an information bottleneck. Flat fan-out from one orchestrator is almost always better than deep nesting.

### Agent-as-tool
**What.** An agent is exposed to another agent as a callable tool — the parent agent invokes it like any other function. The child agent runs its own loop internally, returns a result, and the parent continues.
**Use when.** You want to encapsulate a complex multi-step capability (e.g., "research this topic") behind a simple tool interface, so the calling agent doesn't need to understand the internal complexity.
**Advantages.**
- Clean encapsulation; the parent agent's context is not polluted with the child's intermediate steps
**Tradeoffs.**
- Opaque to the parent: if the child fails or returns poor results, the parent has limited ability to diagnose or retry intelligently
- Latency is unpredictable — the parent's tool call may take seconds or minutes depending on the child's loop
**Staff signal.** Set aggressive timeouts on agent-as-tool calls. The parent agent's user is waiting. Return a partial result with a status indicator rather than timing out silently.

### Handoff / delegation and context transfer
**What.** One agent transfers control to another, passing along relevant context. The key engineering challenge is deciding what context to transfer — too little and the receiving agent lacks information, too much and you blow its context window or confuse it.
**Use when.** Specialized agents need to cooperate (e.g., a triage agent hands off to a billing specialist agent).
**Advantages.**
- Receiving agent gets a clean, focused context rather than inheriting the full messy history
**Tradeoffs.**
- Context summarization at handoff is lossy; critical details may be dropped
- Handoff routing errors send the user to the wrong specialist
**Staff signal.** Define a structured handoff payload (not free-text summary): user intent, key entities, constraints, and what has already been tried. This is more robust than asking the LLM to summarize.

## Lifecycle and operability

### Termination conditions
**What.** An agent must stop. Conditions: the model signals task completion, maximum step count reached, cost/token budget exhausted, the model's output is unchanged for N consecutive steps (no-progress), or a loop is detected (identical tool calls with identical arguments).
**Use when.** Every agent — this is the single most under-designed aspect in practice.
**Advantages.**
- Prevents runaway cost; provides predictable upper bounds on latency and spend
**Tradeoffs.**
- Aggressive limits may cut off the agent before it solves hard problems; too-loose limits waste money
**Staff signal.** Implement all five conditions simultaneously. Max-steps is your safety net; no-progress detection is what actually fires in production. Log why the agent stopped — this is your most valuable diagnostic signal.

### Stuck-loop detection and breaking
**What.** Agents sometimes enter degenerate loops: calling the same tool with the same arguments repeatedly, or oscillating between two states. Detection: hash recent (action, arguments) tuples and check for repeats. Breaking: inject a meta-prompt ("You have called X three times with the same input. Try a different approach or conclude."), remove the tool temporarily, or force termination.
**Use when.** Any production agent without continuous human supervision.
**Advantages.**
- Prevents unbounded cost from degenerate runs
**Tradeoffs.**
- Aggressive loop detection can interrupt legitimate retries (e.g., polling a service that was temporarily down)
**Staff signal.** Distinguish between "same action, same args" (likely stuck) and "same action, different args" (likely progressing). Only the former is a loop.

### Human-in-the-loop
**What.** Inserting human judgment into the agent loop: approval gates before destructive actions, escalation when model confidence is low, and async human steps where the agent pauses and waits for human input.
**Use when.** The agent performs actions with real-world consequences (financial transactions, customer communications, infrastructure changes).
**Advantages.**
- Limits blast radius; builds user trust; satisfies compliance requirements
**Tradeoffs.**
- Humans are slow (seconds to hours): the agent architecture must support pause/resume
- Approval fatigue: too many gates and humans rubber-stamp everything, defeating the purpose
**Staff signal.** Make the approval UI show the agent's reasoning, not just the action. Humans approve better when they understand why, and this also serves as an implicit evaluation of the agent's reasoning quality.

### Interruptibility, pause/resume, and long-running agents
**What.** Agents that run for minutes or hours must be interruptible (user cancels), pausable (waiting for human input or external event), and resumable (continue from where they stopped after a restart or crash).
**Use when.** Any agent that outlives a single request-response cycle.
**Advantages.**
- Enables real-world workflows (code review agents, research agents, overnight batch processing)
**Tradeoffs.**
- Requires serializable agent state, durable storage, and an execution model that can reconstruct context on resume
**Staff signal.** Design the agent's state as a serializable event log from day one. Reconstructing state from the log is how you get both resume and debuggability. This is the same insight as event sourcing in distributed systems.

### Statefulness and checkpointing
**What.** Where the agent's state lives between steps. Options: in-memory (fast, lost on crash), durable queue/database (survives crashes), or a workflow engine (Temporal-style, with automatic retry and checkpointing). Checkpointing means persisting the agent's state at each step so it can resume after failure.
**Use when.** Any agent with more than ~3 steps or any agent that performs side effects.
**Advantages.**
- Crash recovery without re-executing completed (possibly side-effecting) steps
- Enables audit trails and debugging
**Tradeoffs.**
- Serialization cost per step; storage cost for long-running agents; schema evolution of checkpoint format
**Staff signal.** Checkpoint the action log (what was done), not the LLM context (what was said). On resume, you can reconstruct context from the action log and re-prompt the model, which is more robust than trying to serialize model state.

### Idempotency and safe replay
**What.** Agent actions that write to external systems must be idempotent — safe to execute more than once without changing the result beyond the first application. Implementation: idempotency keys on API calls, check-before-write patterns, upserts instead of inserts.
**Use when.** Any agent that performs mutations (database writes, API calls, file modifications).
**Advantages.**
- Safe retry after crash or network failure; enables checkpoint-and-resume
**Tradeoffs.**
- Not all external APIs support idempotency keys; some operations are inherently non-idempotent (sending an email)
**Staff signal.** For non-idempotent actions, use a "did it happen?" check before retry. For truly irreversible actions (send email, charge card), require human approval, which also serves as a natural idempotency gate.

### Determinism boundaries
**What.** Keep all side effects behind an explicit, testable execution layer. The LLM emits a structured action description; your code validates and executes it. This boundary is where you enforce permissions, rate limits, and schema validation.
**Use when.** Always — this is not optional; it is the foundational architectural pattern for safe agents.
**Advantages.**
- You can test the execution layer with deterministic unit tests, independently of the model
- You can mock the execution layer for agent integration tests
**Tradeoffs.**
- Requires disciplined separation; the temptation is to inline execution in the agent loop
**Staff signal.** The execution layer is your primary security boundary. Every permission check, rate limit, and audit log lives here. If you have one architectural rule for agents, it is: the model proposes, your code disposes.

### Cost and latency budgeting
**What.** Setting per-run and per-step caps on tokens, wall-clock time, and dollar cost. Implementation: track cumulative tokens and cost in the agent loop; terminate when budget is exceeded.
**Use when.** Any production agent — without budgets, a single confused run can consume your monthly inference spend.
**Advantages.**
- Predictable cost; enables capacity planning and pricing
**Tradeoffs.**
- Requires per-model cost tracking; multi-model agents complicate accounting
**Staff signal.** Set budgets at the product level (user-facing feature), not just the infrastructure level. "This agent run may cost up to $X" is a product decision that should flow down to the step-level caps.

### Streaming intermediate progress
**What.** Streaming the agent's actions, tool calls, and partial results to the user as they happen, rather than waiting for the final result. This is a UX requirement that drives architectural decisions (event-driven output, SSE/WebSocket transport).
**Use when.** Any user-facing agent that takes more than ~3 seconds to complete.
**Advantages.**
- Users trust agents they can see working; silence beyond a few seconds feels like a hang
- Enables early cancellation if the agent is heading in the wrong direction
**Tradeoffs.**
- Requires streaming-capable infrastructure end-to-end; adds complexity to the transport layer
- Exposing raw tool calls may confuse non-technical users
**Staff signal.** Design two levels of streaming: a technical trace (for developers/debugging) and a user-facing narration (summarized progress). The user-facing stream should describe what the agent is doing, not show raw function calls.

### Framework vs build-your-own
**What.** Agent frameworks provide the core loop, tool registration, memory abstractions, and multi-agent orchestration out of the box. Building your own gives you full control. What frameworks actually give you: boilerplate reduction, community patterns, and pre-built integrations. What they cost: lock-in, abstraction leakage, debugging through framework internals, and opinionated choices that may not fit your use case.
**Use when.** Evaluating how to start a new agent project.
**Advantages.**
- Frameworks accelerate prototyping; valuable for exploration and PoCs
**Tradeoffs.**
- Most production teams outgrow frameworks within 6-12 months and either fork them or replace them with custom orchestration code
- Debugging agent failures through framework abstractions is significantly harder than debugging your own loop
**Staff signal.** The core agent loop is ~50-100 lines of code. The value of a framework is not the loop — it is the ecosystem (tool integrations, memory providers, tracing). Evaluate frameworks on ecosystem breadth and escapability (can you replace one component without rewriting everything?), not on the loop itself.

## Common interview traps

- **Calling everything an "agent."** If the control flow is hard-coded, it's a workflow with LLM steps — and that's usually better. Say so explicitly.
- **Ignoring termination design.** Candidates describe the happy path but not how the agent stops. Always discuss max steps, budget, and loop detection.
- **Proposing tree search for user-facing features.** The cost and latency make this impractical for interactive use. Mention this proactively.
- **Treating reflection as free improvement.** Each reflection cycle is a full LLM call with diminishing returns. Quantify the expected benefit.
- **Defaulting to a deep agent hierarchy.** Every level of hierarchy adds latency, cost, and information loss. Flat is almost always better.
- **Forgetting that the model never executes anything.** The runtime executes; the model proposes. This boundary is where all security lives.
- **Not mentioning cost.** Every agent design discussion should include per-run cost estimates. "5 steps × ~1K tokens each × $X/1M tokens" is the minimum.
- **Treating framework choice as the main architectural decision.** The framework is not the architecture. The control-flow spectrum (workflow ↔ agent) and the tool/permission design are what matter.

## Drill questions

1. A product manager asks you to build an agent for customer onboarding that follows 8 well-defined steps. How do you push back on the "agent" framing, and what do you build instead?
2. Your agent occasionally enters a loop calling the same API 50+ times. Describe three complementary mechanisms to detect and break this, and how you'd implement each.
3. Compare the cost and reliability profile of a 3-wide voting pattern vs one call plus one reflection pass. Under what conditions does each win?
4. You need a research agent that takes 5-30 minutes per run. Walk through the state management design: checkpointing, resume after crash, idempotency of external actions.
5. An agent has 40 available tools. Accuracy of tool selection is dropping. How do you restructure without reducing capability?
6. Describe how you would set per-run cost budgets for a multi-model agent (router uses a small model, workers use a large model). Where does the budget enforcement live?
7. Your orchestrator-worker agent produces poor results. How do you diagnose whether the problem is the orchestrator's decomposition, the workers' execution, or the orchestrator's synthesis?
8. When would you choose plan-then-execute over interleaved planning? What changes if the user must approve the plan?
9. Design the streaming UX for an agent that searches the web, reads documents, and writes a report. What does the user see at each step? What do you hide?
10. A team wants to use a popular agent framework. What three questions do you ask to evaluate whether the framework is appropriate for production, and what answers would make you say "build your own"?
