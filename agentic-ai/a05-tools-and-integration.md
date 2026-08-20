# A5. Tools, Function Calling & Integration (incl. MCP)

Tools are the agent's interface to the outside world — every read, write, search, and mutation flows through a tool call. Architecturally, tools define both the agent's capability envelope and its blast radius. The model never executes anything: it emits a structured request, your runtime validates and executes it, and the result is returned into the context. This boundary is the single most important security and reliability surface in any agent system. This section covers the mechanics of tool calling, schema design, operational concerns, and the emerging standards for tool interoperability.

## Quick-reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Tool-calling mechanics | End-to-end flow from schema to execution | Implementing function calling for the first time |
| Tool schema design | Naming, typing, descriptions as prompt engineering | Designing tool interfaces for LLM consumption |
| Tool description budget | Descriptions consume prompt tokens | Tool count grows and accuracy drops |
| Tool selection at scale | Mitigating degraded accuracy with many tools | Agent has 20+ tools and picks wrong ones |
| Parallel tool calls | Multiple calls in one turn | Independent operations the model can batch |
| Tool result formatting | Managing token cost of outputs | Tools return large payloads |
| Error handling for tools | Structured errors the model can act on | Tool calls fail and the agent must recover |
| Idempotency keys | Safe retry for side effects | Tools that mutate external systems |
| Read vs mutating tools | Permission tiers and dry-run | Limiting blast radius |
| Confirmation gates | Human approval for destructive actions | Deletes, payments, irreversible mutations |
| Timeouts and rate limits | Per-tool resource governance | Preventing runaway or abusive tool use |
| Sandboxing | Isolation for code execution | Agent runs arbitrary code |
| Computer-use / browser agents | GUI automation by models | Tasks requiring web interaction |
| MCP (Model Context Protocol) | Standardized tool/resource exposure | Integrating third-party tools at scale |
| Tool versioning | Backward compatibility as model depends on schemas | Evolving tool APIs without breaking agents |
| Tool call observability | Arguments, results, latency, error rates | Debugging agent behavior (primary surface) |
| Testing tools | Contract tests, golden calls | Validating tools independently of the model |
| Mocking tools for agent tests | Deterministic agent testing | Integration tests that must be reproducible |
| API design for agents | Coarse-grained, error-verbose interfaces | Building APIs meant for LLM consumption |
| Cost attribution | Per-tool-call cost tracking | Understanding where agent spend goes |
| Async/long-running tools | Job submit + poll pattern | Tools that take minutes to complete |

## Mechanics and schema

### Tool-calling end-to-end
**What.** The flow: (1) tool schemas (name, description, parameter JSON schema) are included in the system prompt or a dedicated tool-definition section; (2) the model emits a structured tool-call object (function name + arguments as JSON); (3) YOUR runtime parses, validates (schema check, permission check, rate limit), and executes the call; (4) the result is serialized and appended to the conversation as a tool-result message; (5) the model receives the result and decides the next step. The model never executes anything — it only produces text that your code interprets.
**Use when.** Implementing any agent or tool-using LLM application. This is the foundational pattern.
**Advantages.**
- Clean separation of concerns: model handles reasoning, runtime handles execution and safety
- Execution layer is deterministic and testable independently of the model
**Tradeoffs.**
- Round-trip latency per tool call (model inference + execution + model inference)
- Tool results consume context tokens, reducing remaining budget for reasoning
**Staff signal.** The validation step between model output and execution is your primary security boundary. Never skip it, even for "safe" tools. Validate argument types, ranges, and permissions on every call. A model can hallucinate arguments that your schema allows but your business logic should not.

### Tool schema design
**What.** Tool names should be verb-noun (search_documents, create_ticket). Descriptions function as prompt text — they are the model's only documentation for when and how to use the tool. Parameter typing should be as strict as possible: use enums instead of free-text strings for categorical inputs, mark required vs optional explicitly, and provide examples in descriptions.
**Use when.** Designing any tool interface for LLM consumption.
**Advantages.**
- Well-designed schemas dramatically reduce tool-use errors; the description is effectively prompt engineering
- Strict typing catches hallucinated arguments at the validation layer
**Tradeoffs.**
- Over-detailed descriptions consume prompt tokens; under-detailed ones cause misuse
- Enum parameters reduce flexibility — new enum values require schema updates and redeployment
**Staff signal.** Write tool descriptions as if you're writing API docs for a junior developer who can't ask follow-up questions. Include: what it does, when to use it vs alternatives, what each parameter means, and what the return value looks like. This investment pays back in every call.

### Tool descriptions as prompt budget
**What.** Every tool's schema and description is injected into the prompt (or an equivalent mechanism). With 30 tools averaging 200 tokens each, you spend 6,000 tokens before the conversation even starts. This reduces the context available for the actual task and can degrade model performance.
**Use when.** Your agent has a growing number of tools and you notice accuracy dropping or context limits being hit.
**Advantages.**
- Awareness of this cost lets you optimize early
**Tradeoffs.**
- Reducing descriptions to save tokens makes tool selection less accurate — there is a real tension
**Staff signal.** Monitor the ratio of tool-description tokens to total context. When tool descriptions exceed ~15-20% of available context, restructure: use per-phase tool subsets, retrieval over tools, or a hierarchical tool menu.

### Tool selection at scale
**What.** As tool count grows beyond ~15-20, models increasingly select the wrong tool or hallucinate non-existent tools. Mitigations: (1) retrieval-augmented tool selection — embed tool descriptions and retrieve the top-K relevant tools per query; (2) namespacing/grouping — organize tools into categories and present only the relevant category; (3) per-phase subsets — different agent phases see different tool sets; (4) hierarchical menus — a "meta-tool" that lists available tool categories, then the model selects a category before seeing specific tools.
**Use when.** Agent has more than ~15-20 tools, or you observe tool-selection errors in production.
**Advantages.**
- Keeps per-turn tool count manageable; improves selection accuracy
- Reduces prompt token cost per turn
**Tradeoffs.**
- Retrieval adds latency; hierarchical selection adds an extra LLM round-trip
- Per-phase subsets require you to model the agent's phases explicitly
**Staff signal.** Retrieval over tools is the most scalable approach but introduces a retrieval-quality dependency. Test tool retrieval recall independently: if the right tool isn't in the retrieved set, the agent cannot succeed regardless of reasoning quality.

### Parallel tool calls
**What.** Some models can emit multiple tool calls in a single turn when the calls are independent. The runtime executes them concurrently and returns all results together, saving round-trips.
**Use when.** The agent needs to perform multiple independent operations (e.g., search three databases simultaneously).
**Advantages.**
- Reduces total latency (parallel execution vs sequential round-trips)
**Tradeoffs.**
- The model may incorrectly parallelize dependent calls; your runtime should detect and serialize if needed
- Error handling is more complex: partial failure of a parallel batch requires deciding whether to return partial results or retry
**Staff signal.** Support parallel calls in your runtime even if you don't enable them initially — the execution layer should handle batches natively. This makes it trivial to enable later and also supports manual batching.

## Results and error handling

### Tool result formatting
**What.** Tool outputs go into the context window. Large outputs (full database query results, entire web pages) consume tokens rapidly and can push out important earlier context. Techniques: truncate to a token limit with an indicator ("... 47 more results"), paginate (return first page with a "next page" tool), summarize large outputs with a cheap model before injecting into context.
**Use when.** Any tool that can return variable-length output.
**Advantages.**
- Keeps context budget under control; prevents context overflow on a single tool result
**Tradeoffs.**
- Truncation may remove information the model needs; summarization adds latency and cost
- Pagination requires the agent to learn to paginate, adding loop complexity
**Staff signal.** Set a hard token cap on tool results at the runtime level, not per-tool. This guarantees that no single tool call can blow the context budget regardless of what the tool returns. Then optimize individual tools to return useful information within that cap.

### Error handling for tools
**What.** When a tool call fails, return a structured error to the model (error type, message, actionable suggestion) rather than crashing the agent run. The model can often recover: retry with different arguments, try an alternative tool, or report the limitation to the user. Retry policy: distinguish transient errors (retry with backoff) from permanent errors (report to model immediately).
**Use when.** Any tool can fail — this is not optional.
**Advantages.**
- Enables self-healing: the model can adapt to failures without human intervention
- Structured errors give the model enough information to make good recovery decisions
**Tradeoffs.**
- The model may retry indefinitely if errors are not clearly marked as permanent; combine with retry caps
- Verbose error messages consume context tokens
**Staff signal.** Return errors in the same schema as success results, with an explicit `error` field. Include what went wrong and what the model could try differently. "Permission denied on table X; you only have access to tables Y and Z" is actionable. "Error 403" is not.

### Idempotency keys for side-effecting tools
**What.** Attach a unique idempotency key to every mutating tool call. If the agent retries (due to a crash, timeout, or loop), the external system recognizes the duplicate and returns the original result instead of performing the action again.
**Use when.** Any tool that creates, updates, or deletes external resources.
**Advantages.**
- Safe retry after crash; enables checkpoint-and-resume without double-execution
**Tradeoffs.**
- External APIs must support idempotency keys (many do: Stripe, most cloud APIs; some do not)
- Idempotency windows expire — a retry after hours may not be idempotent
**Staff signal.** Generate idempotency keys at the agent runtime level, not inside the tool. This ensures the key is tied to the agent step, not the tool implementation, and survives tool refactoring.

## Safety and isolation

### Read-only vs mutating tools; permission tiers
**What.** Categorize tools into read-only (search, query, lookup) and mutating (create, update, delete). Apply permission tiers: read tools run freely, mutating tools require higher authorization, destructive tools require human confirmation. Dry-run/preview patterns: the mutating tool returns what it *would* do without executing, allowing the model (or user) to confirm.
**Use when.** Designing the tool permission model for any production agent.
**Advantages.**
- Limits blast radius; most agent loops need reads far more than writes
- Dry-run enables "show me before you do it" UX patterns
**Tradeoffs.**
- Permission tiers add complexity to the tool registration system
- Dry-run doubles the round-trips for confirmed actions (preview + execute)
**Staff signal.** Default to read-only. Require explicit opt-in for mutating tools, and treat each mutating tool as a security-reviewed surface. In many production agents, the model has read-only tools and can only propose mutations that a separate system (or human) executes.

### Confirmation gates for destructive actions
**What.** Before executing a destructive action (delete account, send email, charge payment), the agent pauses and presents the action to a human for approval. Implementation: the tool returns a "pending_confirmation" status, the agent communicates this to the user, and resumes upon approval.
**Use when.** Any action that is irreversible or has significant real-world consequences.
**Advantages.**
- Prevents catastrophic errors; builds user trust
**Tradeoffs.**
- Adds latency (human response time); requires async-capable agent architecture
- Approval fatigue if too many actions require confirmation
**Staff signal.** Make confirmation selective and risk-weighted. "Delete 3 test records" might auto-approve; "delete production database table" always requires confirmation. The risk classification is a product decision, not a model decision.

### Timeouts, rate limits, and quotas
**What.** Per-tool enforcement: maximum execution time (timeout), maximum calls per time window (rate limit), and maximum total calls per agent run (quota). Prevents a confused agent from hammering an external API or a slow tool from blocking the entire run.
**Use when.** Any production agent with external tool calls.
**Advantages.**
- Protects external systems from agent-driven abuse; bounds cost and latency
**Tradeoffs.**
- Aggressive timeouts can kill legitimate long-running operations; must tune per-tool
**Staff signal.** Enforce rate limits at the runtime level, not inside individual tools. This gives you a single point of control and a unified observability surface.

### Sandboxing for code execution
**What.** When agents run arbitrary code (generated by the model), execute it in an isolated environment: containers, VMs, or serverless functions with restricted filesystem, network egress, CPU/memory limits, and execution time caps. No access to the host, secrets, or other tenants' data.
**Use when.** Any agent that runs model-generated code (data analysis, code generation, shell commands).
**Advantages.**
- Contains the blast radius of arbitrary code; prevents data exfiltration and resource exhaustion
**Tradeoffs.**
- Sandbox startup latency (cold start of container/VM); limits on available libraries and tools inside the sandbox
**Staff signal.** The sandbox is not optional — it is the minimum security boundary for code execution. Default-deny network egress; whitelist specific endpoints. The most common exfiltration vector is the model encoding data into a DNS query or HTTP request to an attacker-controlled domain.

### Computer-use / browser automation
**What.** Agents that control a browser or GUI through screenshots, accessibility trees, or DOM interaction. The model observes the screen, decides what to click/type, and the runtime executes the action.
**Use when.** Automating tasks on websites that lack APIs, or testing web applications.
**Advantages.**
- Can interact with any web UI without API access
**Tradeoffs.**
- Extremely brittle: UI changes break automation. High latency (screenshot per action). Expensive (vision model calls). Error recovery is poor — the model often cannot recover from an unexpected dialog or page state.
**Staff signal.** Prefer APIs over computer-use in every case where an API exists. Computer-use is a last resort, not a feature to build products on. Its reliability profile (~70-85% task completion on benchmarks as of early 2026) is not sufficient for production workflows without human oversight.

## Standards and interoperability

### Model Context Protocol (MCP)
**What.** MCP is an open protocol that standardizes how tools, resources (data), and prompt templates are exposed to LLM applications. It uses a client-server architecture: the LLM application (client/host) connects to one or more MCP servers, each of which exposes a set of tools with standardized schemas. Transports include stdio (local) and HTTP with SSE (remote).
**Use when.** Integrating with third-party tool providers, or exposing your own tools/data as a reusable capability that multiple agents can consume.
**Advantages.**
- Standard interface reduces per-integration engineering effort; tool provider builds once, all MCP clients can consume
- Separates tool hosting from agent hosting
**Tradeoffs.**
- Third-party MCP servers are a trust boundary: they receive your data (tool arguments) and return results that enter the model's context. Malicious or compromised servers can inject adversarial content.
- Protocol adds a network hop and serialization overhead per tool call
**Staff signal.** Treat third-party MCP servers with the same scrutiny as third-party API integrations: audit what data you send, validate what you receive, enforce timeouts, and monitor for behavioral changes. The convenience of plug-and-play tools does not eliminate supply-chain risk.

## Operations and testing

### Tool versioning and backward compatibility
**What.** When you change a tool's schema (rename a parameter, change a return format), agents that depend on the old schema may break. Treat tool schemas as contracts: version them, maintain backward compatibility, and deprecate gracefully.
**Use when.** Any tool that is used in production and may evolve.
**Advantages.**
- Prevents agent breakage from schema changes
**Tradeoffs.**
- Maintaining multiple schema versions increases complexity
**Staff signal.** The model may have learned tool-use patterns during fine-tuning that depend on specific schema shapes. Even if your runtime accepts the new schema, the model may not use it correctly until prompted or retrained. Test tool-use accuracy after any schema change.

### Tool call observability
**What.** Log every tool call: function name, arguments, result (or error), latency, and cost. This is the primary debugging surface for agents — most agent failures manifest as wrong tool calls, wrong arguments, or unexpected results.
**Use when.** Always. This is not optional in production.
**Advantages.**
- Enables root-cause analysis of agent failures; feeds into evaluation and monitoring
- Enables cost attribution per tool
**Tradeoffs.**
- Tool results may contain sensitive data; logging must respect PII policies and redaction rules
**Staff signal.** Structure tool-call logs as structured events, not free-text. This enables querying ("show me all calls to search_documents that returned zero results in the last hour") which is where operational insight comes from.

### Testing tools independently; mocking for agent tests
**What.** Test each tool with contract tests (does it conform to its schema?) and golden-call tests (known inputs produce known outputs). For agent integration tests, mock/stub tools to return deterministic outputs, isolating the test to the agent's reasoning and tool selection.
**Use when.** Building any test suite for an agent system.
**Advantages.**
- Contract tests catch tool regressions before they reach the agent; mocking enables reproducible agent tests
**Tradeoffs.**
- Mocks may diverge from real tool behavior over time; supplement with periodic end-to-end tests against real tools
**Staff signal.** The most valuable agent test is a "golden trajectory" test: given this input and these mocked tool responses, does the agent take the expected sequence of actions? This tests the reasoning, not the tools, which is what you actually want to validate.

### API design for agent consumption
**What.** APIs designed for LLM consumption differ from human-facing APIs: prefer coarse-grained operations (one call does more work), verbose error messages (the model needs to understand what went wrong), structured output (JSON over HTML), and explicit field descriptions. Avoid paginated results where possible; return summaries instead.
**Use when.** Building backend APIs that agents will call as tools.
**Advantages.**
- Reduces the number of tool calls (cost, latency) and improves model accuracy
**Tradeoffs.**
- Coarse-grained APIs may be less flexible for other consumers; consider separate agent-facing endpoints
**Staff signal.** The best agent API is one the model almost never calls incorrectly. Measure tool-call error rate per API endpoint and redesign the ones with the highest error rates — the model is telling you the API is confusing.

### Cost attribution per tool call
**What.** Track the cost of each tool call: LLM tokens consumed for the call and result, external API costs, compute costs for execution. Aggregate per tool, per agent run, and per user.
**Use when.** Managing agent costs in production.
**Advantages.**
- Identifies the most expensive tools; enables optimization targeting
**Tradeoffs.**
- Attribution is imperfect: the token cost of a tool result is shared with subsequent reasoning steps
**Staff signal.** The majority of agent cost is usually concentrated in 1-2 tools that return large results. Find them and optimize their output format first — this typically yields more savings than optimizing the number of tool calls.

### Long-running / async tools
**What.** Some tools take minutes or hours (ML training, report generation, external approval workflows). Pattern: the tool call returns immediately with a job ID, and the agent has a separate poll/check tool to query job status. Alternatively, the agent pauses and is woken by a callback when the job completes.
**Use when.** Integrating with any backend process that cannot return results in seconds.
**Advantages.**
- Agent is not blocked waiting; can perform other work or pause and resume cheaply
**Tradeoffs.**
- Polling adds LLM calls (cost); callbacks require durable agent state management
**Staff signal.** Prefer callbacks over polling. Each poll iteration is an LLM round-trip that costs money and consumes context. If you must poll, implement it in the runtime (not in the model's reasoning loop) to avoid token waste.

## Common interview traps

- **Saying the model "calls" a function.** It does not. It emits text that your runtime interprets and executes. This distinction is the entire security model.
- **Ignoring tool description token cost.** Candidates add tools freely without accounting for the prompt budget impact.
- **Not mentioning tool-selection degradation at scale.** Every serious agent deployment hits this; discuss mitigation strategies proactively.
- **Treating all tool calls as equal risk.** Read-only and mutating tools have fundamentally different safety profiles. State this.
- **Skipping error handling.** Tools fail. The model needs structured, actionable errors — not stack traces.
- **Assuming MCP is a trust mechanism.** It is an interoperability protocol, not a security protocol. Third-party MCP servers are untrusted by default.
- **Not discussing idempotency.** Any agent that can crash and retry must address idempotent execution.
- **Describing computer-use as production-ready.** Its reliability and cost profile make it a last resort, not a default choice.

## Drill questions

1. Walk through the complete lifecycle of a tool call, from schema injection through execution to result handling. Where does validation happen and what does it check?
2. Your agent has 40 tools and increasingly selects wrong ones. Describe three architectural approaches to fix this, with tradeoffs of each.
3. A tool call to an external payment API fails midway. How does your idempotency strategy prevent double-charging? What if the API doesn't support idempotency keys?
4. Design the error response format for tools so the model can distinguish transient from permanent failures and take appropriate action.
5. You're integrating a third-party MCP server for calendar access. What security and operational concerns do you raise in a design review?
6. How do you test an agent's tool-selection logic independently of the tools themselves? Describe the test setup and what it validates.
7. Your agent generates and runs Python code. Describe the sandbox architecture: isolation, resource limits, network policy, and how you handle the model trying to exfiltrate data.
8. A tool returns 50KB of JSON. Walk through your options for getting this into the model's context effectively, with cost and accuracy tradeoffs.
9. You need to add a new required parameter to an existing tool. How do you roll this out without breaking agents currently using the old schema?
10. Compare the cost and reliability profile of using a browser-automation agent vs an API integration for the same task. When is browser automation justified?
