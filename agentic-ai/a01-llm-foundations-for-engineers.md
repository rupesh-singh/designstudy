# A1. LLM Foundations for System Builders

Large language models are not magic text boxes — they are inference engines with
specific computational, memory, and cost profiles that directly constrain every
architectural decision you make. This file covers the model-level behaviours an
engineer must understand to design systems that are fast, affordable, reliable,
and predictable. You do not need to know how to train models; you need to know
why your 128K-context request costs 30× more than a 4K one, why output tokens
are slower than input tokens, and why temperature=0 still gives you different
answers on Tuesday.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Tokens & tokenization | Unit of cost, latency, and limits | Estimating cost, hitting context limits, debugging non-English bloat |
| Context window | Maximum working memory per request | Designing prompt layout, deciding what fits |
| Autoregressive decoding | Output is generated one token at a time | Explaining why generation is slow, why streaming helps |
| Prefill vs decode phases | Two-phase execution with different bottlenecks | Diagnosing TTFT vs throughput problems |
| KV cache | Per-request memory that grows with context | Capacity planning, understanding OOM under concurrency |
| TTFT / ITL / total latency | Three latency metrics that move independently | Setting SLOs, choosing streaming vs batch |
| Throughput vs latency | Batching trades latency for throughput | Sizing inference fleet, choosing batch strategy |
| Sampling controls | Temperature, top-p, top-k govern randomness | Tuning creativity vs determinism per use case |
| Non-determinism | Same input can yield different output | Designing tests, caching, reproducibility |
| Structured output | Constraining output to valid JSON/schema | Building reliable tool-calling and data extraction |
| Function/tool calling | Model emits a call; your code executes it | Connecting LLMs to APIs, databases, tools |
| Reasoning models | Extra test-time compute for harder problems | Deciding when to spend more on thinking |
| Model tiers | Base vs instruct vs reasoning models | Choosing the right model for each task |
| Model routing / cascades | Cheap model first, escalate if needed | Cutting cost while preserving quality |
| Prompt caching | Reusing KV cache for shared prefixes | Reducing TTFT and cost for repeated prompts |
| Hallucination | Confident generation of false content | Designing grounding, verification, guardrails |
| Context degradation | Quality drops with length and position | Placing critical info, choosing context size |
| Token cost model | Input vs output vs cached pricing | Budgeting per-request and per-user cost |
| Rate limits (TPM/RPM) | Provider-imposed capacity ceilings | Architecting for quota, retry, and failover |
| Multimodality | Text/image/audio in one model | Estimating cost/latency for vision or audio tasks |

---

## Computational model of inference

### Tokens and tokenization
**What.** Tokenization splits text into sub-word units (tokens) that the model operates on. Every cost, latency, and context-length limit is denominated in tokens, not characters or words. A typical English-language ratio is roughly 1 token per 0.75 words, but code, non-Latin scripts, and structured formats (JSON, XML) inflate significantly — a CJK sentence may consume 2–3× the tokens of an equivalent English one, and deeply nested JSON burns tokens on braces and keys.
**Use when.** Estimating cost before launch, debugging why a prompt "doesn't fit," or understanding why your Korean product costs more per query.
**Advantages.**
- Provides a universal unit for budgeting cost, latency, and capacity across providers
- Sub-word tokenization handles open-vocabulary input without out-of-vocabulary failures
**Tradeoffs.**
- Token boundaries are invisible to users; truncation can split mid-word or mid-codepoint
- Tokenizer is model-specific — token counts differ between model families; you need the right tokenizer library for accurate estimates
**Staff signal.** A cost model that uses "average tokens per request" will be wrong for multilingual or code-heavy workloads. Always profile token counts on *your actual traffic distribution*, and budget headroom for the long tail.

### Context window
**What.** The context window is the maximum number of tokens a model can accept (input + output) in a single request. It functions as the model's entire working memory — anything outside it does not exist for that call. Typical sizes range from ~4K to ~1M+ tokens depending on model, but usable quality often degrades well before the hard limit.
**Use when.** Deciding how to partition information across prompt sections, whether to use RAG vs stuffing, and when to split a task into sub-calls.
**Advantages.**
- Larger windows reduce the need for external retrieval for moderate-sized corpora
- Enables processing entire documents or codebases in one pass
**Tradeoffs.**
- Cost and latency scale with total tokens consumed, not just output; a 128K input is not free
- Quality degrades in the middle of very long contexts (see "context degradation" below)
- The window must hold system prompt + tools + retrieved docs + history + output; it fills faster than you expect
**Staff signal.** Context window is a *budget*, not a capacity to fill. Experienced engineers treat it like memory allocation: they track how many tokens each section consumes and set hard caps per section, dropping or summarizing the least-critical content first.

### Autoregressive decoding
**What.** LLMs generate output one token at a time, each conditioned on all prior tokens (both input and previously generated output). This sequential dependency is why output generation is inherently slower per token than input processing and why you cannot trivially parallelize generation.
**Use when.** Explaining why a 500-token response takes meaningfully longer than reading 500 tokens of input, or why streaming is beneficial.
**Advantages.**
- Enables streaming — you can send tokens to the user as they are produced, improving perceived latency
- Each token is conditioned on the full preceding context, producing coherent output
**Tradeoffs.**
- Output tokens are generated serially; generation time is roughly proportional to output length
- Cannot "skip ahead" to generate only the answer; the model must produce every token in sequence
**Staff signal.** When designing for latency, the key lever is *output token count*, not input. A system that asks the model to "think step by step" may produce 5× more output tokens and therefore 5× the generation time. Budget output length explicitly.

### Prefill vs decode phases
**What.** Inference happens in two phases. *Prefill* processes all input tokens in parallel (compute-bound, uses GPU math units heavily). *Decode* generates output tokens one at a time (memory-bandwidth-bound, reading the KV cache each step). This distinction explains nearly all LLM latency behaviour: TTFT is dominated by prefill, and per-token generation speed is dominated by decode.
**Use when.** Diagnosing whether your latency problem is "slow to start" (prefill-bound, long prompt) or "slow to finish" (decode-bound, long output).
**Advantages.**
- Understanding these phases lets you optimize the right bottleneck — bigger GPU for prefill, more memory bandwidth for decode
- Disaggregated serving architectures separate prefill and decode onto different hardware
**Tradeoffs.**
- Optimizing one phase can worsen the other; e.g., large batch sizes improve prefill throughput but compete for memory bandwidth during decode
- Disaggregated serving adds network overhead and architectural complexity
**Staff signal.** If your workload is "short prompt, long generation" (e.g., creative writing), you are decode-bound and should optimize for memory bandwidth. If it is "long prompt, short answer" (e.g., document Q&A), you are prefill-bound and benefit from prompt caching or faster compute.

### KV cache
**What.** During generation, the model caches the key and value tensors for every attention layer and every token processed so far. This avoids re-computing attention over the full context at each decoding step. The KV cache size grows linearly with context length and model size, and each concurrent request needs its own cache.
**Use when.** Capacity planning for inference servers, understanding why you get OOM errors under concurrency, or evaluating long-context cost.
**Advantages.**
- Makes autoregressive decoding computationally feasible by avoiding quadratic recomputation
- Enables efficient generation once prefill is done
**Tradeoffs.**
- Memory consumption grows with context_length × num_layers × hidden_dim × 2 (keys + values) × batch_size; at 128K context a single request can consume tens of GB of GPU memory
- Limits maximum concurrent requests (batch size) on a given GPU — more memory per request means fewer parallel users
- Techniques like paged attention (vLLM-style) reduce fragmentation but not total memory
**Staff signal.** The KV cache is why "just use 128K context" is not free even if the model supports it. Your serving cost is dominated by how many concurrent requests fit in GPU memory. Shorter effective context = more concurrent users = lower cost per query. This is the economic argument for RAG over context stuffing.

---

## Latency and throughput

### TTFT, ITL, and total latency
**What.** *Time to first token (TTFT)* measures how long until the first output token arrives — dominated by prefill. *Inter-token latency (ITL)*, also called time per output token (TPOT), measures the gap between successive output tokens — dominated by decode. *Total latency* = TTFT + (output_tokens × ITL). These three metrics move independently and demand different optimizations.
**Use when.** Setting SLOs for an LLM-powered product, deciding whether to stream, or diagnosing where latency budget is spent.
**Advantages.**
- Decomposing latency this way lets you optimize the binding constraint rather than guessing
- TTFT is the key metric for perceived responsiveness in streaming UIs
**Tradeoffs.**
- Optimizing for TTFT (e.g., smaller batches, prompt caching) may reduce throughput
- Very low ITL targets may require overprovisioned hardware with high memory bandwidth
**Staff signal.** For interactive applications, the user-perceived metric is *TTFT + first-meaningful-content latency*, not total latency. Streaming masks decode time. For batch/backend workloads, total tokens per second (throughput) matters more than TTFT. Choose your SLO metric to match your UX.

### Throughput vs latency tradeoff; continuous batching
**What.** Batching multiple requests together improves GPU utilization and throughput (tokens per second across all requests) but increases latency for individual requests. *Continuous (in-flight) batching* allows new requests to join a batch as others finish, avoiding the "wait for slowest" problem of static batching. This is the standard in modern serving frameworks.
**Use when.** Sizing your inference fleet, choosing a serving framework, or understanding why latency spikes under load.
**Advantages.**
- Continuous batching dramatically improves GPU utilization compared to naive one-at-a-time serving
- Allows trading off latency vs cost smoothly by adjusting max batch size
**Tradeoffs.**
- Larger batches increase per-request latency, especially ITL, because decode steps now serve more sequences
- Under high load, queuing delay compounds on top of batch latency
**Staff signal.** When latency spikes under load, the root cause is almost always batching + queuing, not "the model got slower." Monitor queue depth and batch size as first-class metrics, not just p50/p99 latency.

---

## Controlling output

### Sampling controls: temperature, top-p, top-k
**What.** These parameters shape the probability distribution before a token is sampled. *Temperature* scales logits — lower values sharpen the distribution toward the most likely token; higher values flatten it. *Top-p* (nucleus sampling) truncates to the smallest set of tokens whose cumulative probability exceeds p. *Top-k* truncates to the k most likely tokens. They are applied in combination.
**Use when.** Tuning the creativity–determinism spectrum per task: near-zero temperature for classification/extraction, moderate for conversational, higher for brainstorming.
**Advantages.**
- Cheap, zero-latency way to control output diversity without changing the prompt
- Combining top-p and temperature gives fine-grained control
**Tradeoffs.**
- Temperature=0 (greedy) sounds deterministic but is *not guaranteed* across different serving infrastructure, GPU types, or even request batching — floating-point non-determinism in parallel computation can flip token choices at near-tied probabilities
- Very high temperature produces incoherent output; very low temperature can get stuck in repetitive loops
**Staff signal.** Never build a system that assumes temperature=0 is deterministic. If you need reproducible output for caching or testing, you must hash on the prompt and accept that two runs may differ. Design your cache to tolerate this.

### Non-determinism as a first-class engineering problem
**What.** Even with identical prompts and temperature=0, LLM output can vary across requests due to floating-point arithmetic differences in batched/distributed computation, model version updates, and infrastructure changes. This is not a bug — it is an inherent property.
**Use when.** Designing tests, caches, audit logs, or any system that expects repeatable output.
**Advantages.**
- Acknowledging non-determinism forces robust design: semantic assertions, fuzzy matching, range-based validation
- Frees you from the fragile assumption that LLM output is a pure function
**Tradeoffs.**
- Snapshot-based golden-test approaches break; you need evaluation-based testing instead
- Caching by prompt hash will sometimes serve stale or slightly-wrong results when the model is updated
**Staff signal.** The staff-level move is to separate *semantic correctness* testing (does the output meet the requirement?) from *exact-match* testing (is the output identical to a snapshot?). Use LLM-as-judge or structured-output validation for the former; never rely solely on the latter.

### Structured output: JSON mode, constrained decoding, schema-guided generation
**What.** Structured output mechanisms force the model to produce syntactically valid output conforming to a schema. *JSON mode* guarantees valid JSON. *Constrained decoding* (grammar-guided generation) restricts token sampling at each step to only tokens that continue a valid parse. *Schema-guided generation* validates against a JSON Schema. These operate at different layers: some are server-side, some are API-level guarantees.
**Use when.** Any time you parse model output programmatically — tool calls, data extraction, structured reasoning traces.
**Advantages.**
- Eliminates an entire class of parsing errors and retry loops
- Constrained decoding has near-zero latency overhead since it only masks logits
**Tradeoffs.**
- Constraining the output format does not constrain the *content* — the JSON may be valid but semantically wrong
- Complex schemas with many optional fields or unions can degrade generation quality as the constraint space confuses the model
- Not all providers support the same schema subset; portability is limited
**Staff signal.** Constrained decoding guarantees *syntax*, not *semantics*. You still need validation on field values — e.g., an enum field will be syntactically valid but the model might pick the wrong enum value. Layer schema validation + semantic validation + retry.

### Function/tool calling
**What.** Tool calling is a model capability where the model, given descriptions of available tools (functions), can emit a structured request to invoke one. Critically: *the model does not execute anything*. It produces a JSON blob saying "call function X with arguments Y." Your application runtime receives this, executes the actual function, and feeds the result back. The model then continues generating with the result in context.
**Use when.** Connecting an LLM to external APIs, databases, calculators, code execution — any capability beyond text generation.
**Advantages.**
- Cleanly separates the model's reasoning (what to call and with what arguments) from execution (your code, with your auth, your error handling)
- Enables composable agent architectures where the model is a control plane
**Tradeoffs.**
- Tool descriptions consume context tokens; dozens of tools can fill a significant fraction of the window
- The model can hallucinate tool names, invent non-existent parameters, or call tools in wrong order
- Parallel tool-call support varies by provider and model
**Staff signal.** The most common interview misunderstanding: candidates say "the model calls the API." It does not. The model *requests* a call. Your runtime *decides* whether to execute it, with what permissions, with what timeout, and what to do if it fails. This boundary is where your security and reliability controls live.

---

## Model selection and routing

### Reasoning / "thinking" models and test-time compute
**What.** Reasoning models allocate additional compute at inference time by generating extended internal chain-of-thought before producing a final answer. This "thinking" phase burns extra output tokens (sometimes thousands), increasing both latency and cost, but significantly improves performance on math, logic, multi-step planning, and complex code generation.
**Use when.** Tasks where accuracy on hard problems outweighs latency and cost — complex code generation, mathematical reasoning, multi-step planning, safety-critical decisions.
**Advantages.**
- Substantially higher accuracy on tasks requiring multi-step reasoning
- The thinking trace is often inspectable, aiding debugging and trust
**Tradeoffs.**
- Latency can be 5–20× higher than a standard model on the same task due to the extended thinking phase
- Cost scales with thinking tokens, which can exceed the visible output by an order of magnitude
- Simpler tasks gain no benefit and just burn budget
**Staff signal.** Reasoning models are the "premium tier" in a model cascade. Use them selectively for tasks where a cheaper model demonstrably fails, not as a default. The cost-optimal architecture routes easy tasks to a fast model and only escalates to a reasoning model when confidence is low or the task is classified as complex.

### Base vs instruction-tuned vs reasoning-tuned models
**What.** *Base models* are raw next-token predictors with no conversational ability. *Instruction-tuned models* (via RLHF/DPO/SFT) follow instructions, respect safety guidelines, and converse naturally. *Reasoning-tuned models* add extended thinking capabilities. Each tier adds capability and cost.
**Use when.** Choosing which model tier to use for a given task in your system.
**Advantages.**
- Matching model tier to task avoids overpaying: classification tasks rarely need a reasoning model; creative tasks rarely need a base model
- Base models can be fine-tuned for narrow tasks at lower cost than instruction-tuned models
**Tradeoffs.**
- Base models require careful prompting (they complete text, they don't follow instructions) and are unsuitable for user-facing chat
- Reasoning models cost more per token and have higher latency; using them for simple tasks wastes budget
**Staff signal.** In a production system with diverse tasks, you typically need at least two tiers: a fast instruction-tuned model for simple classification/extraction/routing, and a capable reasoning model for complex planning and generation. One model for everything is either too slow/expensive or too inaccurate.

### Model routing / cascades
**What.** A model cascade sends each request to the cheapest model first. If the result meets a quality threshold (measured by confidence scores, structural validation, or a lightweight judge), it is returned. Otherwise, the request is escalated to a more capable (and expensive) model. Routing can also be done upfront by classifying the request's difficulty.
**Use when.** You have heterogeneous traffic where most requests are easy but some are hard, and you want to optimize cost without sacrificing quality on the hard ones.
**Advantages.**
- Can reduce average cost by 50–80% compared to always using the best model, if most traffic is simple
- Improves average latency since the fast model responds more quickly for easy cases
**Tradeoffs.**
- Adds architectural complexity: you need a routing/classification layer and quality-assessment logic
- Failed escalation (cascade miss) means double latency — cheap model attempt + expensive retry
- The quality threshold itself needs tuning and monitoring; false positives waste money, false negatives degrade quality
**Staff signal.** The hardest part of a cascade is building a reliable confidence signal. Self-reported model confidence is poorly calibrated. Prefer structural checks (did the output parse? did it match the schema? did it contain a citation?) over asking the model "are you sure?" Build the cascade to be observable so you can tune the escalation rate over time.

---

## Cost, caching, and efficiency

### Prompt caching (prefix caching)
**What.** Prompt caching stores the KV cache computed during prefill for a prompt prefix and reuses it for subsequent requests that share the same prefix. This skips the expensive prefill computation for the shared portion. It requires that the cacheable content appears at the *beginning* of the prompt (system prompt, tool definitions, static instructions).
**Use when.** You have a stable system prompt, tool definitions, or large static context that is shared across many requests.
**Advantages.**
- Reduces TTFT substantially for long shared prefixes (the cached portion is essentially free prefill)
- Providers typically charge reduced rates for cached input tokens (often ~50% or more discount)
**Tradeoffs.**
- Forces a specific prompt layout: stable content must come first, variable content last — this constrains prompt engineering
- Cache has a TTL and eviction policy; low-volume use cases may not benefit if the cache is cold
- Changing a single token in the prefix invalidates the cache for everything after it
**Staff signal.** Prompt caching inverts the usual prompt-design instinct. Without caching, you might put the user query first and context second. With caching, you put the *stable* system prompt and tool definitions first, then per-user context, then the query last. This layout difference can cut costs dramatically at scale.

### Token cost model
**What.** LLM providers charge per token, typically with different rates for input tokens, output tokens, and cached input tokens. Output tokens are more expensive (often 2–4×) because they require the sequential decode process. Cached input tokens are cheaper because they skip prefill. Your cost per request = (input_tokens × input_price) + (output_tokens × output_price) - cache_savings.
**Use when.** Budgeting per-request cost, estimating monthly spend, comparing model options.
**Advantages.**
- Token-based pricing is transparent and measurable; you can instrument exact costs per request
- Optimizing prompt length and output length directly reduces cost
**Tradeoffs.**
- Output tokens cost more but are harder to control (the model decides how much to say)
- Cost can vary dramatically by task: a summarization request with a 10K-token input and 200-token output costs differently than a generation request with a 500-token input and 2K-token output
**Staff signal.** The most impactful cost lever is usually *output token count*, not input. Setting max_tokens and instructing the model to be concise can cut cost significantly. The second lever is prompt caching for shared prefixes. The third is model routing to avoid using expensive models for easy tasks.

### Rate limits as a capacity constraint
**What.** Providers impose rate limits measured in tokens per minute (TPM) and requests per minute (RPM). These are hard ceilings that return 429 errors when exceeded. They function as a capacity constraint that must be designed around, not just retried through.
**Use when.** Architecting for scale, designing retry/backoff logic, planning multi-provider failover.
**Advantages.**
- Forces you to think about capacity planning and queuing early, which prevents cascade failures at scale
- Multiple provider accounts or multi-model strategies can aggregate quota
**Tradeoffs.**
- Bursty traffic patterns hit RPM limits even when average throughput is well under TPM limits
- Retry storms after a 429 can amplify the problem; exponential backoff with jitter is essential
- Higher rate limits are often tied to higher-tier (more expensive) pricing plans
**Staff signal.** Rate limits shape architecture more than most engineers realize. They are why you need request queues, priority lanes (user-facing requests before background jobs), and multi-provider failover. Treat TPM/RPM as a first-class resource to be managed, like database connections or memory.

---

## Reliability and failure modes

### Hallucination
**What.** Hallucination is when a model generates fluent, confident text that is factually wrong or unsupported by its input. It happens because the model is optimizing for plausible next-token predictions, not factual accuracy — it has no internal fact-checker, no concept of truth, only learned statistical patterns.
**Use when.** Designing any system where factual accuracy matters, which is most production systems.
**Advantages.**
- Understanding the mechanism (statistical generation, not retrieval) clarifies that hallucination is inherent, not a bug to be "fixed" — it must be *mitigated*
**Tradeoffs.**
- Mitigations (grounding via RAG, constrained output, verification chains, citation requirements) all add latency and cost
- No single mitigation eliminates hallucination entirely; defense in depth is required
**Staff signal.** The engineering mitigations, in order of effectiveness: (1) ground the model in retrieved source material and require citations, (2) constrain output to structured formats where values can be validated, (3) use a verification step (second model call or deterministic check) on critical claims, (4) make the model say "I don't know" via prompt engineering. Layer these; never rely on a single one.

### Context degradation / lost-in-the-middle
**What.** LLMs do not attend equally to all positions in the context window. Information placed in the middle of a long context is recalled less reliably than information at the beginning or end. Quality also degrades generally as context length increases, even for models that technically support very long windows.
**Use when.** Deciding where to place critical information in a prompt, sizing context for RAG, or choosing between stuffing and retrieval.
**Advantages.**
- Knowing this pattern lets you place the most important content (instructions, key facts) at the beginning and end of the prompt
- Justifies shorter, curated context over blindly stuffing the full window
**Tradeoffs.**
- Mitigating by placing info at edges limits prompt layout flexibility
- Very long contexts are unreliable enough that RAG with selective retrieval often outperforms context stuffing for large corpora
**Staff signal.** "Our model supports 1M tokens" does not mean you should use 1M tokens. Effective context length is shorter than advertised context length. Benchmark your specific task at various context sizes; you will often find a point of diminishing (or negative) returns well before the maximum.

### Multimodality
**What.** Multimodal models accept and/or produce multiple modalities — text, images, audio, video. Images are typically encoded as a grid of visual tokens; a single image can consume hundreds to thousands of text-equivalent tokens. Audio is similarly tokenized. This means multimodal inputs have radically different cost and latency profiles than text alone.
**Use when.** Building systems that process images (OCR, visual Q&A, UI understanding), audio (transcription, voice agents), or video.
**Advantages.**
- Eliminates the need for separate vision or audio pipelines in many cases; one model handles reasoning across modalities
- Enables tasks like "describe this screenshot" or "answer based on this chart" natively
**Tradeoffs.**
- A single high-resolution image can consume as many tokens as several pages of text, dramatically increasing cost and prefill latency
- Image token counts depend on resolution settings; high-detail mode is much more expensive than low-detail
- Audio tokens accumulate continuously; a one-minute audio clip is many thousands of tokens
**Staff signal.** When designing multimodal systems, the dominant cost/latency driver is usually the image or audio input, not the text. Downsizing images, using low-detail modes for tasks that don't need pixel-level accuracy, and transcribing audio to text before sending to the LLM are all valid cost optimizations. Always compare the cost of the multimodal path vs a specialized model (e.g., a dedicated OCR or ASR model) for your specific accuracy requirement.

---

## Common interview traps

- **"Temperature=0 is deterministic."** It is not. Floating-point non-determinism in parallel/batched computation means identical prompts can produce different outputs, especially at near-tied token probabilities.
- **"The model calls the API."** No. The model emits a tool-call request; your runtime executes it. This boundary is where all security, auth, and error-handling logic must live.
- **"128K context means I can process 128K tokens of documents."** The window must also hold the system prompt, tool definitions, conversation history, and the generated output. Actual usable document space is much less.
- **"Longer context is always better."** Quality degrades with length (lost-in-the-middle), cost grows linearly, and KV cache memory limits concurrency. Sometimes shorter, better-curated context outperforms a full dump.
- **"Output tokens cost the same as input tokens."** Output tokens are typically 2–4× more expensive and are the primary driver of generation latency due to sequential decoding.
- **"I'll just use the best model for everything."** Model routing/cascades can reduce cost by 50%+ with minimal quality degradation on easy tasks. One-model-fits-all is the expensive default.
- **"Structured output guarantees correct output."** It guarantees *syntactically valid* output. The values inside the valid JSON can still be wrong, hallucinated, or semantically invalid.
- **"Prompt caching just happens automatically."** It requires specific prompt layout (stable prefix first) and has cache TTL/eviction. You must design your prompts to be cache-friendly.
- **"Reasoning models are always better."** They are slower and costlier. For simple tasks, they offer no benefit and just burn budget. Use them selectively.
- **"Latency is just one number."** TTFT, ITL, and total latency are independent metrics driven by different bottlenecks. Optimizing the wrong one wastes effort.

## Drill questions

1. Your RAG system processes 10K-token documents with a 200-token answer. Is this workload prefill-bound or decode-bound? How does this change your infrastructure choices?
2. You are serving 100 concurrent users with a 32K context window. What limits your batch size, and what happens if you double the context length?
3. Design a cost model for a customer-support chatbot. What are the three most impactful levers for reducing per-conversation cost?
4. A developer reports that their "deterministic" pipeline (temperature=0) produces different outputs across deployments. Explain why, and design a testing strategy that accommodates this.
5. You have 50 tools registered in your agent. Each tool description averages 200 tokens. What fraction of a 128K context window is consumed by tool definitions alone, and what would you do about it?
6. Your product team wants to add image understanding to an existing text chatbot. Walk through the cost and latency implications.
7. When would you route a request to a reasoning model vs a standard instruction-tuned model? How would you build the router?
8. Explain why prompt caching forces a specific prompt layout. Design the layout for a multi-tenant customer-support agent.
9. Your system's p99 TTFT is 3 seconds but p50 is 400ms. What are the likely causes, and how would you investigate?
10. A model cascade routes 80% of traffic to a cheap model and 20% to an expensive one. The expensive model sometimes gets a request that already failed on the cheap model. What is the latency implication, and how do you mitigate it?
11. You need to extract structured data (name, date, amount) from invoices. Compare constrained decoding vs JSON mode vs post-hoc parsing with retries. Which do you choose and why?
12. Your monthly LLM bill is dominated by output tokens. What architectural changes would you explore to reduce it?
