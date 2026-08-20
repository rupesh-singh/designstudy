# A2. Prompting & Context Engineering

Context is a managed resource with a budget, not a string you write once. Every
token in the context window has an opportunity cost — it displaces something else
that could be there. Prompt engineering is authoring the static instructions;
context engineering is the systems discipline of dynamically assembling, sizing,
compacting, and versioning the full context payload across many requests,
conversations, and users. The shift from "prompt engineering" to "context
engineering" reflects the move from artisanal prompt-writing to building
repeatable, testable pipelines that manage context programmatically.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Prompt vs context engineering | From static text to dynamic context assembly | Architecting any multi-turn or RAG-backed system |
| Message roles & hierarchy | system / developer / user / assistant / tool | Designing instruction precedence and security boundaries |
| Zero-shot vs few-shot | Examples in-prompt for steering output format | Output format is ambiguous or the model under-performs without examples |
| Chain-of-thought (CoT) | Eliciting step-by-step reasoning | Complex reasoning tasks; deciding if the token cost is justified |
| ReAct | Interleaved reasoning and tool-use pattern | Designing agent loops that think before acting |
| Structured prompt formatting | Delimiters, XML tags, named sections | Improving reliability and reducing prompt sensitivity |
| Output format specification | Defining and validating expected output shape | Any programmatic consumption of model output |
| Context budget allocation | Partitioning tokens across sections | Fitting everything into a finite window |
| Context compaction | Summarization, windowing, hierarchical compression | Long conversations or large knowledge bases |
| Context isolation via subagents | Delegating to a child agent with its own context | Keeping a parent agent's context clean |
| Prompt templating | Parameterized prompts with safe interpolation | Reusable prompts across users and requests |
| Prompt versioning & registry | Treating prompts as versioned, deployable artifacts | Managing prompt changes across environments |
| Prompt regression testing | Automated tests for prompt behaviour | CI/CD pipelines for prompt changes |
| A/B testing prompts | Comparing prompt variants in production | Optimizing quality or cost with real traffic |
| Prompt sensitivity | Small edits → large behaviour changes | Debugging unexpected behaviour after minor prompt changes |
| Multi-turn state management | What to keep verbatim vs summarize | Long conversations, agent loops |
| System prompt design for agents | Role, constraints, tool policy, termination rules | Building agent-based systems |
| Guard text vs enforcement | "Please don't" is not a control | Security-critical prompt design |
| Token budgeting & truncation | What to drop first when context is full | Operating near context limits |
| Multilingual considerations | Non-English token inflation and behaviour | Serving global users |

---

## The context engineering mindset

### Prompt engineering vs context engineering
**What.** Prompt engineering is crafting the text of instructions to an LLM. Context engineering is the broader systems discipline of dynamically selecting, assembling, ordering, sizing, and versioning *everything* that goes into the context window — system instructions, tool definitions, retrieved documents, conversation history, scratchpad, and the user's input. Context engineering treats the context window as a managed resource with a token budget.
**Use when.** Building any production LLM application beyond a single-turn demo. The shift happens the moment you have retrieval, tools, multi-turn history, or multiple users.
**Advantages.**
- Moves prompt work from artisanal craft to an engineering discipline with testable, reproducible pipelines
- Forces explicit budgeting, preventing the "everything goes in" approach that silently degrades quality
**Tradeoffs.**
- Adds infrastructure complexity: template engines, budget allocators, truncation logic, versioning systems
- Requires measuring token counts for each section, which adds latency to context assembly
**Staff signal.** Prompt engineering skills plateau; context engineering is where the architectural leverage is. The engineer who asks "how do I write a better prompt?" is at one level; the engineer who asks "how do I dynamically allocate my 128K token budget across six content sources with different staleness requirements?" is at a much more impactful level.

### Message roles: system / developer / user / assistant / tool
**What.** Modern chat APIs structure context as a sequence of typed messages. *System* or *developer* messages set the model's behaviour, personality, and constraints with elevated instruction priority. *User* messages are the end-user's input. *Assistant* messages are the model's prior responses (or pre-filled responses). *Tool* messages carry function call results. The instruction hierarchy (system > user) means the model is trained to prioritize system-level instructions over user-level requests.
**Use when.** Designing the structure of any LLM interaction, especially when security matters (preventing prompt injection from user content).
**Advantages.**
- The hierarchy provides a defence layer: system instructions are harder for user input to override
- Typed messages make the conversation structure machine-readable and versionable
**Tradeoffs.**
- The hierarchy is a *trained preference*, not a hard security boundary — sufficiently adversarial user input can still override system instructions
- Different providers implement roles slightly differently; portability requires abstraction
**Staff signal.** Never treat the system/user role boundary as a security wall. It is a *mitigation* — one layer in a defence-in-depth strategy. Combine it with output validation, tool-call authorization, and content filtering. If your system's safety depends entirely on the system prompt, it is under-engineered.

---

## Prompting techniques

### Zero-shot vs few-shot; dynamic few-shot retrieval
**What.** *Zero-shot* prompting provides instructions but no examples. *Few-shot* prompting includes example input-output pairs in the prompt to demonstrate the desired format and reasoning pattern. *Dynamic few-shot* selects examples at runtime from a bank, typically using embedding similarity to the current input, so examples are maximally relevant.
**Use when.** The model's zero-shot output doesn't match your desired format or quality. Few-shot is especially useful for classification, extraction, and format-sensitive tasks.
**Advantages.**
- Few-shot examples often improve output consistency more reliably than lengthy instructions
- Dynamic selection avoids wasting tokens on irrelevant examples
**Tradeoffs.**
- Each example consumes context tokens; 5 examples at 200 tokens each is 1,000 tokens of budget
- Example quality matters enormously — bad examples teach bad patterns
- Dynamic retrieval adds latency (embedding + lookup) to context assembly
**Staff signal.** The underappreciated cost of few-shot is the *opportunity cost* of the tokens. Those 1,000 tokens could hold retrieved documents, more history, or additional tool definitions. Dynamic few-shot + shorter examples is the staff-level move: you get the benefit of examples with minimal budget waste.

### Chain-of-thought (CoT); self-consistency
**What.** Chain-of-thought prompting asks the model to show its reasoning steps before giving a final answer. This improves accuracy on math, logic, and multi-step problems by forcing the model to "work through" the problem in its output tokens. *Self-consistency* samples multiple CoT paths and takes a majority vote, further improving accuracy at the cost of multiple inference calls.
**Use when.** Tasks involving reasoning, calculation, or multi-step logic where accuracy matters more than cost.
**Advantages.**
- Significant accuracy improvements on reasoning tasks, often for free (just add "think step by step")
- Self-consistency turns variance into a feature by aggregating across it
**Tradeoffs.**
- CoT generates many more output tokens, increasing both latency and cost (output tokens are the expensive ones)
- Self-consistency multiplies cost by the number of samples (typically 3–10×)
- On simple tasks (classification, extraction), CoT adds cost without improving accuracy
**Staff signal.** CoT is not free. Every reasoning token is an output token billed at the higher rate. The staff-level question is always: "does CoT improve accuracy on *this specific task* enough to justify the 3–5× output token increase?" Measure it; don't assume.

### ReAct (reason + act) as a prompting pattern
**What.** ReAct interleaves reasoning (thinking about what to do) and acting (calling tools or taking actions) in alternating steps. The model first reasons about what information it needs or what action to take, then emits a tool call, then reasons about the result, and continues. This produces interpretable traces of agent decision-making.
**Use when.** Building agent loops that need to make decisions about tool use, multi-step workflows, or information gathering.
**Advantages.**
- Produces auditable reasoning traces — you can see *why* the agent chose each action
- Interleaving reasoning with observations prevents the model from planning too far ahead without grounding in real data
**Tradeoffs.**
- Each reasoning step consumes output tokens; a 10-step ReAct trace can be very expensive
- The model may "overthink" and produce redundant reasoning steps
**Staff signal.** ReAct is the default agent prompting pattern, but you must bound it. Set a maximum number of iterations, a total token budget for reasoning, and a timeout. Unbounded ReAct loops are a classic cost and latency runaway. Also: the reasoning tokens in ReAct are *visible* output tokens charged at the output rate — they are not free "thinking" like in dedicated reasoning models.

### Structured prompt formatting
**What.** Using explicit delimiters (XML-style tags, markdown headers, triple backticks, labeled sections) to structure prompts improves the model's ability to parse and follow instructions reliably. Structure reduces ambiguity about which content is instructions vs data vs examples.
**Use when.** Any prompt longer than a few sentences, especially those mixing instructions with data.
**Advantages.**
- Measurably reduces instruction-following failures compared to unstructured prose
- Makes prompts machine-readable: your code can assemble and validate sections programmatically
**Tradeoffs.**
- Tags and delimiters consume tokens (usually negligible compared to the reliability gain)
- Overly complex nesting can confuse the model
**Staff signal.** This is one of the highest-ROI prompting techniques. If your prompt mixes instructions, data, and examples in unstructured prose and you're getting inconsistent results, adding clear section delimiters (e.g., `<instructions>`, `<context>`, `<examples>`) is almost always the first thing to try.

### Output format specification and validation loops
**What.** Explicitly defining the expected output format (JSON schema, enum values, field names) in the prompt, combined with programmatic validation of the output and retry on failure. This creates a generate-validate-retry loop that converges on correct output.
**Use when.** Any time you parse model output programmatically. Pair with structured output modes (JSON mode, constrained decoding) when available.
**Advantages.**
- Retry loops tolerate occasional format failures, turning a flaky model into a reliable data source
- Separates format correctness (automated) from semantic correctness (harder to check)
**Tradeoffs.**
- Retries add latency and cost; typically cap at 2–3 retries before failing
- Infinite retry loops on fundamentally broken prompts are a cost hazard
**Staff signal.** The retry loop needs a *different* failure path than just "try again." On retry, include the validation error in the prompt ("Your output was invalid: missing field 'amount'. Please try again.") — this makes the model correct the specific mistake rather than generating a completely new (possibly differently broken) output.

---

## Context as a managed resource

### Context budget allocation
**What.** The context window must hold several competing sections: system instructions, tool definitions, retrieved documents, conversation history, scratchpad/reasoning space, and the user's current input, plus reserved space for the model's output. Context budget allocation is the practice of assigning a maximum token count to each section and enforcing it.
**Use when.** Any application where the sum of all context sources could exceed the window, which is nearly all production applications.
**Advantages.**
- Prevents silent quality degradation from overfilling the context
- Makes context composition deterministic and testable
**Tradeoffs.**
- Requires measuring token counts for each section, which adds complexity to the context assembly pipeline
- Fixed allocations may be suboptimal; some requests need more retrieval and less history, or vice versa
**Staff signal.** The typical allocation priority (drop-first order) is: old conversation history → retrieved documents (keep top-ranked, drop lower) → few-shot examples → tool definitions → system instructions (never drop). Dynamic allocation based on the current request type is more sophisticated but significantly more complex. Start with fixed budgets, then move to dynamic allocation only if the quality improvement justifies the complexity.

### Context compaction: summarization, rolling windows, hierarchical summaries
**What.** When conversation history or accumulated context exceeds the budget, compaction techniques reduce it while preserving the most important information. *Rolling windows* keep only the last N turns. *Summarization* uses an LLM to compress older history into a summary. *Hierarchical summaries* maintain summaries at multiple granularities (per-turn, per-topic, per-session).
**Use when.** Long-running conversations, agent loops with many iterations, or any system where history grows unbounded.
**Advantages.**
- Enables arbitrarily long conversations without hitting context limits
- Summarization preserves semantic content at a fraction of the token cost
**Tradeoffs.**
- Summarization itself requires an LLM call, adding latency and cost to context assembly
- Information is inevitably lost; the question is whether the lost information mattered
- Summarization can introduce errors or drift — the summary may misrepresent what actually happened
**Staff signal.** The hardest part of compaction is knowing *what is safe to drop*. User preferences stated early in a conversation ("I'm allergic to peanuts") must be preserved even when old turns are summarized. The staff-level design includes a "pinned facts" mechanism — extracted key-value pairs that persist independently of summarized history.

### Context isolation via subagents
**What.** Instead of loading everything into a single agent's context, delegate subtasks to child agents that each run with their own isolated context window. The parent agent receives only the child's output (a summary or result), keeping its own context clean and focused.
**Use when.** Complex workflows with multiple information-heavy subtasks that would collectively overwhelm a single context window.
**Advantages.**
- Each subagent gets a full, clean context window focused on its subtask
- Parent agent's context stays small and focused on orchestration, not details
- Failures in one subagent don't pollute the parent's context with error traces
**Tradeoffs.**
- Each subagent call incurs additional latency and cost (a full LLM inference per subagent)
- Information transfer between parent and child is lossy — the parent only sees what the child returns
- Orchestration logic to fan out, collect, and reconcile subagent results adds complexity
**Staff signal.** Context isolation is the "microservices of prompting" — it solves context bloat at the cost of coordination overhead. The design question is the same as in service decomposition: what is the right granularity? Too many subagents waste tokens on setup and coordination; too few overload a single context. Use subagents for *information-heavy* subtasks (e.g., "analyze this 50-page document") and keep *logic-light* tasks in the parent.

---

## Prompt lifecycle and operations

### Prompt templating and injection-safe interpolation
**What.** Prompt templates are parameterized prompts where variables (user input, retrieved data, tool results) are interpolated at runtime. *Injection-safe interpolation* treats all interpolated values as untrusted data — wrapping them in delimiters, escaping, or placing them in lower-priority message roles — to prevent prompt injection.
**Use when.** Any production system where user input or external data is included in the prompt.
**Advantages.**
- Templates enable reuse, testing, and versioning of prompts across environments
- Injection-safe patterns reduce the risk of adversarial user input overriding system instructions
**Tradeoffs.**
- No interpolation scheme is 100% injection-proof; it is a mitigation, not a guarantee
- Overly aggressive escaping or wrapping can garble legitimate input
**Staff signal.** The injection-safe principle: *never concatenate untrusted strings directly into system-level instructions*. Place user input in the `user` message role, wrap external data in explicit delimiters (`<user_input>...</user_input>`), and validate model output before acting on it. This is the LLM equivalent of parameterized SQL queries — the pattern that prevents injection.

### Prompt versioning, registry, and prompts as deployable artifacts
**What.** In production systems, prompts should be versioned, stored in a registry, and deployed like code — with version numbers, changelogs, rollback capability, and environment-specific variants (dev/staging/prod). A prompt registry is a service that stores and serves prompts by name and version.
**Use when.** Any team with more than one person modifying prompts, or any system where prompt changes need to be auditable and reversible.
**Advantages.**
- Enables rollback when a prompt change degrades quality
- Decouples prompt deployment from code deployment, enabling faster iteration
**Tradeoffs.**
- Adds infrastructure: a registry service, deployment pipeline, and version management
- Can lead to prompt sprawl if not managed; dozens of prompt versions across environments
**Staff signal.** The key insight is that prompts change more frequently than code but affect behaviour just as much. If you deploy code through CI/CD but edit prompts by hand in a config file, you have a governance gap. Treat prompts with the same rigour as code: pull requests, review, automated testing, staged rollout.

### Prompt regression testing and CI gates
**What.** Automated tests that run a prompt against a curated set of inputs and assert on output quality using evaluation criteria (not exact-match). These tests run in CI on prompt changes and gate deployment.
**Use when.** Any prompt that is modified iteratively — which is all production prompts.
**Advantages.**
- Catches regressions before they reach production; a changed system prompt that breaks tool calling is caught in CI
- Forces the team to define "what does good output look like" explicitly
**Tradeoffs.**
- LLM evaluation is inherently noisy; tests must use statistical thresholds (e.g., "pass rate > 90% on 50 test cases") rather than exact assertions
- Test suites are expensive to run (each test case is an LLM call) and slow (seconds per case)
- False negatives (tests that miss real regressions) and false positives (tests that fail on good prompts) both require tuning
**Staff signal.** The staff-level trap is writing exact-match assertions on LLM output. These are fragile and uninformative. Use semantic assertions: "output contains a valid JSON object with field X," "output does not mention competitor Y," "LLM-as-judge rates output as helpful ≥ 4/5." Build a regression suite of 30–100 diverse cases that covers your critical paths.

### A/B testing prompts in production
**What.** Running two or more prompt variants simultaneously on live traffic and comparing their performance on business metrics (task completion, user satisfaction, cost, latency). Requires traffic splitting, metric collection, and statistical analysis.
**Use when.** Optimizing prompt quality, format, or cost on real user traffic where offline evaluation is insufficient.
**Advantages.**
- Measures real-world impact, not just offline benchmarks
- Can discover that a cheaper/shorter prompt performs equally well in production
**Tradeoffs.**
- Requires infrastructure for traffic splitting, variant assignment, and metric attribution
- LLM output variance requires larger sample sizes than typical A/B tests to reach statistical significance
- Users in the "worse" variant have a degraded experience during the test
**Staff signal.** A/B testing prompts is harder than A/B testing UI changes because LLM output has high variance. You need more samples and more robust metrics. Prefer structured metrics (task completion rate, tool-call success rate, parse error rate) over subjective quality scores.

---

## Multi-turn and agent context

### Prompt sensitivity and brittleness
**What.** LLM behaviour can change dramatically from seemingly minor prompt edits — reordering instructions, changing a word, adding whitespace. This brittleness means that prompt changes are high-risk changes that need testing, not casual edits.
**Use when.** Debugging unexpected behaviour changes, planning prompt modifications, or justifying prompt regression testing.
**Advantages.**
- Awareness of brittleness drives rigorous testing practices
- Explains why "just tweak the prompt" is a risky approach to fixing issues
**Tradeoffs.**
- Makes prompt optimization feel unpredictable; changes that "should" help sometimes hurt
- Discourages experimentation if not paired with fast evaluation feedback loops
**Staff signal.** Brittleness is why prompts need CI/CD, not just version control. A one-word change to a system prompt can break tool calling for 5% of requests. Always run your regression suite before deploying prompt changes, even "trivial" ones.

### Multi-turn state: what to keep verbatim vs summarize
**What.** In multi-turn conversations, you must decide which prior turns to keep verbatim (preserving exact wording), which to summarize (compressing to save tokens), and which to drop entirely. This decision depends on the informational value and recency of each turn.
**Use when.** Any multi-turn chat, agent loop, or workflow that accumulates history.
**Advantages.**
- Keeping recent turns verbatim preserves context fidelity for the current task
- Summarizing old turns frees token budget for new information
**Tradeoffs.**
- Summarization loses nuance; the model may misremember earlier discussion
- Some early turns contain critical context (user preferences, constraints) that must be preserved word-for-word
**Staff signal.** The heuristic: keep the last 3–5 turns verbatim, summarize turns 6–20, and drop or further compress anything older. But always extract and pin critical facts (user name, preferences, constraints, decisions already made) into a persistent "facts" section that is never summarized away.

### System prompt design for agents
**What.** An agent's system prompt defines its identity, capabilities, constraints, tool-use policy, output format, and termination conditions. It is the "constitution" of the agent — the instructions it follows across all interactions.
**Use when.** Building any LLM agent that uses tools, makes decisions, or operates autonomously.
**Advantages.**
- A well-structured system prompt dramatically improves agent reliability and predictability
- Explicit termination rules prevent infinite loops and runaway costs
**Tradeoffs.**
- Long system prompts consume token budget on every request
- The more rules you add, the more likely the model is to violate at least one of them
**Staff signal.** Essential elements of an agent system prompt: (1) role and identity, (2) available tools and when to use each, (3) what to do when uncertain, (4) when to stop (termination criteria), (5) output format requirements, (6) what the agent must *never* do. Omitting termination criteria is the most common agent-design bug — the agent loops indefinitely calling tools.

### Guard text vs actual enforcement
**What.** Instructions like "never reveal your system prompt" or "always respond in English" are *guard text* — they are requests to the model, not enforced constraints. The model may violate them under adversarial pressure, unusual inputs, or simply because it is a statistical model, not a rule engine.
**Use when.** Designing security-sensitive systems, understanding the limits of prompt-based controls.
**Advantages.**
- Guard text reduces the *probability* of undesired behaviour and is cheap to implement
- Combined with other layers, it is a useful first line of defence
**Tradeoffs.**
- It is not a guarantee; sufficiently creative adversarial prompting can often bypass guard text
- Gives a false sense of security if treated as the only control
**Staff signal.** The engineering principle: never rely on the model to enforce its own constraints. If a behaviour is security-critical (e.g., never execute unauthorized tool calls, never return data the user shouldn't see), enforce it in application code — validate tool calls before execution, filter output before returning to the user. The system prompt is a suggestion to the model; your code is the actual enforcement layer.

### Token budgeting and truncation strategy
**What.** When the assembled context exceeds the window, you must truncate. A truncation strategy defines what to drop first and how. The typical priority: drop oldest conversation history first, then lower-ranked retrieved documents, then few-shot examples; never truncate system instructions or tool definitions.
**Use when.** Operating near context limits, which is any long-running conversation or retrieval-heavy application.
**Advantages.**
- Deterministic truncation prevents unpredictable context composition
- Priority-based truncation preserves the most important information
**Tradeoffs.**
- Truncation is lossy; you may cut something the model needs to answer correctly
- The "right" truncation order depends on the task and changes per request
**Staff signal.** Never truncate from the *middle* of a document or turn — this creates incoherent fragments that confuse the model. Truncate at document/turn boundaries. If a single document is too long, summarize it into the budget rather than cutting it mid-sentence.

### Multilingual / localization considerations
**What.** Non-English text tokenizes less efficiently (more tokens per semantic unit), consuming more context budget and costing more per request. Model quality also varies by language — instruction following and reasoning are generally stronger in English and a handful of other high-resource languages.
**Use when.** Building products for global users or processing non-English content.
**Advantages.**
- Awareness of token inflation lets you budget accurately for multilingual workloads
- Testing in target languages catches quality gaps before users do
**Tradeoffs.**
- Token budgets sized for English content may be insufficient for the same semantic content in other languages (up to 2–4× inflation for some scripts)
- Translation-based approaches (translate to English → process → translate back) add latency and can lose nuance
**Staff signal.** If your product serves multiple languages, your token budget allocation must account for worst-case token expansion. A 4K-token budget that works for English may need to be 8K for Japanese or Arabic. Test your prompts and evaluate quality in every language you support, not just English.

---

## Common interview traps

- **"Prompt engineering is just writing good prompts."** In production, the bigger problem is dynamically assembling context from multiple sources under a token budget — that is context engineering.
- **"The system prompt is a security boundary."** It is a trained preference, not an enforceable wall. Always pair it with application-level enforcement.
- **"Chain-of-thought always helps."** It wastes output tokens on simple tasks like classification or extraction. Measure before applying.
- **"Just put everything in the context."** Context is a scarce budget. Overfilling degrades quality (lost-in-the-middle) and increases cost. Always curate.
- **"Prompt changes are low-risk."** Small edits can cause large behavioural changes due to prompt sensitivity. Test prompt changes with the same rigour as code changes.
- **"We test prompts with exact-match assertions."** LLM output is non-deterministic. Use semantic assertions and statistical pass rates.
- **"We version prompts in the code repo."** Better than nothing, but decoupling prompt deployment from code deployment (via a prompt registry) enables much faster iteration.
- **"Few-shot examples are always worth the token cost."** They consume budget that could hold retrieved documents or history. Use dynamic selection and keep examples short.
- **"We handle multi-turn by keeping the full conversation."** This works for 5 turns; it fails at 50. You need a compaction strategy.

## Drill questions

1. You have a 128K context window. Your system prompt is 2K tokens, tool definitions are 5K, and you want to support 20-turn conversations. Design the token budget allocation, including when and what to truncate.
2. A prompt change improved accuracy on your test set by 8% but caused a 3% regression in a different task category. How do you decide whether to ship it?
3. Your agent sometimes ignores its system-prompt instruction to "never call the delete API without user confirmation." How do you actually enforce this?
4. You're building a multilingual customer-support chatbot. The same conversation in Japanese uses 2.5× the tokens of the English version. How does this affect your architecture?
5. Design a prompt regression test suite for a document-extraction prompt. What test cases do you include, what assertions do you make, and what pass threshold do you set?
6. An agent is designed with ReAct prompting and averaging 12 reasoning-action steps per task. Each step costs ~500 output tokens. Calculate the token cost per task and propose a design to reduce it without sacrificing quality.
7. Compare rolling-window history truncation vs LLM-based summarization for a long-running chat. When would you choose each?
8. Your team is arguing about whether to use few-shot examples or more detailed instructions to improve output format compliance. What data would you collect to decide?
9. How would you design context isolation for an agent that needs to (a) search a knowledge base, (b) query a database, and (c) compose an email — given that each subtask needs substantial context?
10. Describe a prompt injection attack against a customer-facing chatbot and three layers of defence you would implement.
