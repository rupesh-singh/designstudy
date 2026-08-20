# A11. Inference Infrastructure, Serving & Cost

Every LLM-powered feature is ultimately bounded by inference cost, latency, and availability. Even teams that use managed APIs must understand the infrastructure layer — it determines what is affordable, what latency is achievable, and where cost explodes as agent loops multiply requests. This section equips the engineer to size systems, set budgets, make build-vs-buy calls, and hold informed conversations with platform and ML infrastructure teams.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Managed API vs self-hosted | The foundational build-vs-buy decision | Starting a new LLM-powered product or re-evaluating costs |
| GPU memory math | Weights + KV cache + activations determine hardware needs | Sizing GPU clusters or understanding why a model doesn't fit |
| Batch size as throughput lever | More concurrent requests per GPU = higher throughput | Optimizing serving cost or throughput |
| Continuous batching | Keeps GPUs busy by adding new requests mid-flight | Evaluating inference servers |
| Paged attention / KV cache management | Eliminates memory fragmentation in KV cache | Understanding why long-context or high-concurrency serving is hard |
| Prefix/prompt caching | Reuses computation for shared prompt prefixes | Reducing latency and cost for repetitive system prompts |
| Disaggregated prefill/decode | Splits two inference phases onto different hardware | Optimizing at scale for mixed latency/throughput workloads |
| Speculative decoding | Draft model predicts tokens verified by the main model | Reducing latency without quality loss |
| Tensor/pipeline parallelism | Spreads a model across multiple GPUs | Model too large for one GPU |
| Inference server options | vLLM, TRT-LLM, TGI, SGLang and the selection criteria | Choosing self-hosted serving infrastructure |
| Autoscaling GPU workloads | Scaling GPU instances up and down with demand | Managing cost for variable-traffic workloads |
| Capacity planning | Provisioned vs on-demand throughput | Budgeting and SLA planning |
| Multi-tenancy and fair scheduling | Isolating workloads on shared GPU infrastructure | Multiple teams or customers sharing inference capacity |
| Priority lanes | Interactive vs batch inference separation | Latency-sensitive and latency-tolerant workloads coexist |
| Batch/offline inference | Processing large datasets asynchronously | High-volume, latency-insensitive work |
| Cost model end-to-end | Tokens → requests → tasks → users cost hierarchy | Budgeting and identifying cost hotspots |
| Cost optimization levers | Ranked list of cost-reduction techniques | Cost is the binding constraint |
| Embedding/reranking infrastructure | Separate serving for smaller, high-volume models | RAG retrieval at scale |
| Vector index infrastructure | Memory, build time, replication for vector search | Sizing and operating vector databases |
| Latency budget decomposition | Breaking an agent turn into additive latency components | Diagnosing slow agent responses |
| Edge/on-device inference | Running models locally without API calls | Offline, privacy, or ultra-low-latency requirements |
| Inference observability | Metrics for monitoring inference health | Operating inference in production |

## Build vs Buy

### Managed API vs Self-Hosted Inference
**What.** Managed APIs (e.g., OpenAI, Anthropic, Google, Azure OpenAI) handle all serving infrastructure; self-hosted deploys open-weight models on your own or leased GPUs. This is the most consequential infrastructure decision.
**Use when.** Starting any LLM-powered product, or when costs on managed APIs cross a threshold that triggers re-evaluation.
**Advantages.**
- Managed: zero ops burden, instant access to frontier models, elastic capacity, rapid model upgrades
- Self-hosted: predictable cost at high volume, full data residency control, no rate limits, ability to fine-tune and customize serving
**Tradeoffs.**
- Managed: per-token pricing that scales linearly (no volume discount in many cases), vendor lock-in, rate limits under load, data leaves your network
- Self-hosted: significant upfront investment (GPU procurement/leasing, MLOps team, on-call), slower access to new models, you own availability and security
**Staff signal.** The crossover point where self-hosting becomes cheaper depends on utilization. Managed APIs are priced for convenience; if your GPU utilization exceeds ~60% sustained, self-hosting typically wins on cost. Below that, you are paying for idle GPUs. Model the utilization curve before committing to infrastructure.

## GPU and Memory Fundamentals

### GPU Memory Math
**What.** GPU memory (VRAM) is consumed by three components: model weights, KV cache (grows with context length × batch size), and activation memory (intermediate computation). The sum determines how many GPUs a model needs and how many concurrent requests it can serve.
**Use when.** Sizing hardware for a model deployment or understanding why throughput is lower than expected.
**Advantages.**
- Weights: roughly 2 bytes per parameter in FP16 (a 70B model ≈ 140 GB), reduced proportionally by quantization
- KV cache: scales with (num_layers × hidden_dim × 2 × context_length × batch_size); this is often the dominant consumer at high concurrency or long context
- Understanding the math prevents over- or under-provisioning
**Tradeoffs.**
- Longer context windows and higher concurrency compete for the same memory pool — you cannot maximize both on fixed hardware
- Memory pressure forces a choice between supporting fewer long requests or many short requests
**Staff signal.** Context length is the hidden cost driver. Doubling maximum context length roughly doubles KV cache memory per request, halving the concurrent request capacity of each GPU. When product teams request "support 128k context," the infrastructure team hears "halve our throughput or double our GPUs."

### Batch Size as the Primary Throughput Lever
**What.** GPU efficiency increases with batch size because the memory-bandwidth cost of loading weights is amortized across more tokens. Larger batches produce more tokens per second per GPU at the cost of higher per-request latency.
**Use when.** Tuning inference serving for throughput vs latency targets.
**Advantages.**
- Moving from batch-1 to batch-32 can improve throughput by 10–30× on modern GPUs (approximate)
- Throughput improvements translate directly to lower cost per token
**Tradeoffs.**
- Larger batches increase per-request latency because each request waits for the batch to complete a step
- Memory limits cap maximum batch size; the KV cache for all concurrent requests must fit in VRAM
**Staff signal.** Batch size is the dial between cost efficiency (high batch, high throughput) and user experience (low batch, low latency). Interactive endpoints need small batches; batch processing should maximize batch size. Running both on the same cluster without priority isolation wastes money or hurts latency.

### Continuous / In-Flight Batching
**What.** Traditional batching waits for a full batch before processing. Continuous batching inserts new requests into a running batch as soon as any request completes (frees a slot), keeping the GPU busy without waiting.
**Use when.** Evaluating inference servers — continuous batching is now table-stakes for efficient serving.
**Advantages.**
- Dramatically improves GPU utilization on variable-length requests (short requests do not wait for long ones to finish)
- Reduces average latency compared to static batching
**Tradeoffs.**
- Implementation complexity in the serving engine; scheduling logic must manage variable-length sequences efficiently
- Preemption policies are needed when the batch is full and a high-priority request arrives
**Staff signal.** If your inference server does not support continuous batching, you are leaving 2–5× throughput on the table. This is the single most impactful serving optimization and should be a hard requirement in server selection.

## Memory and Caching Optimizations

### Paged Attention and KV Cache Management
**What.** Paged attention (introduced by vLLM) manages KV cache memory like an operating system manages virtual memory — allocating non-contiguous blocks and mapping them to logical sequences. This eliminates the memory fragmentation that occurs when sequences have variable lengths.
**Use when.** Serving variable-length requests at high concurrency — which is nearly every production workload.
**Advantages.**
- Eliminates memory waste from pre-allocated, fixed-size KV cache slots; can improve effective memory utilization by 2–4×
- Enables higher concurrency on the same hardware
**Tradeoffs.**
- Adds a layer of indirection in memory access; negligible overhead in practice
- Block size tuning affects efficiency — too large wastes memory, too small increases management overhead
**Staff signal.** Paged attention transformed LLM serving economics. Before it, serving was memory-inefficient by default. Any self-hosted deployment should use a server that implements paged attention. If your serving stack pre-allocates fixed KV cache per sequence, you are wasting up to half your GPU memory.

### Prefix/Prompt Caching
**What.** When multiple requests share the same prompt prefix (e.g., a long system prompt), the KV cache for that prefix can be computed once and reused across requests, saving both computation and memory. Some systems use a radix-tree structure to share prefixes of varying lengths.
**Use when.** Your system uses long, repetitive system prompts or few-shot examples across many requests.
**Advantages.**
- Eliminates redundant prefill computation for shared prefixes; can reduce first-token latency and cost by 50%+ for long system prompts
- Managed API providers increasingly offer automatic prompt caching with price discounts on cached tokens
**Tradeoffs.**
- Effectiveness depends on prompt structure — if every request has a unique prefix, caching provides no benefit
- Cache invalidation and memory pressure management add complexity in self-hosted deployments
**Staff signal.** Design your prompt structure with caching in mind. Place static content (system prompt, instructions, few-shot examples) before dynamic content (user query, retrieved documents). This simple ordering maximizes cache hit rates and can cut inference cost significantly.

## Advanced Serving Techniques

### Disaggregated Prefill/Decode Serving
**What.** The two phases of autoregressive inference — prefill (processing the entire prompt in parallel, compute-bound) and decode (generating tokens one at a time, memory-bandwidth-bound) — have different hardware profiles. Disaggregated serving runs them on separate, independently scaled hardware pools.
**Use when.** Operating at large scale where the hardware utilization improvement justifies architectural complexity.
**Advantages.**
- Prefill benefits from high-compute GPUs; decode benefits from high-memory-bandwidth GPUs — separate pools optimize each
- Enables independent scaling: long prompts create prefill pressure, long generations create decode pressure
**Tradeoffs.**
- Requires transferring KV cache between prefill and decode nodes — a networking and latency cost
- Significantly more complex orchestration; premature for most teams
**Staff signal.** Disaggregated serving is a hyperscaler optimization. Unless you are processing millions of requests per day with measurably different prefill/decode bottlenecks, a unified serving pool with continuous batching is the right default.

### Speculative Decoding
**What.** A small, fast "draft" model generates several candidate tokens cheaply, then the full model verifies them in a single forward pass. If the draft tokens are correct (which they often are for predictable text), multiple tokens are produced in the time of one large-model step.
**Use when.** Latency is the binding constraint and throughput is adequate; speculative decoding trades throughput for latency.
**Advantages.**
- Can reduce decode latency by 2–3× for predictable output patterns with no quality degradation (verified tokens are identical to what the large model would have produced)
- Particularly effective for structured outputs (JSON, code) where the draft model's predictions are often correct
**Tradeoffs.**
- Draft model adds memory and compute overhead; net throughput may decrease because the GPU runs two models
- Benefit varies with output predictability — creative, diverse generation benefits less
**Staff signal.** Speculative decoding is free quality (the output is mathematically identical) at the cost of throughput. Use it for latency-sensitive interactive paths; do not use it for batch processing where throughput matters more than per-request latency.

### Tensor and Pipeline Parallelism
**What.** Tensor parallelism splits individual matrix operations across GPUs within a node (fast interconnect required). Pipeline parallelism splits model layers across GPUs, processing micro-batches in a pipeline.
**Use when.** A model's weights exceed the memory of a single GPU and must be spread across multiple devices.
**Advantages.**
- Tensor parallelism: enables models that don't fit on one GPU; near-linear scaling with fast interconnects (NVLink)
- Pipeline parallelism: works across nodes with slower interconnects; better for very large models
**Tradeoffs.**
- Tensor parallelism requires high-bandwidth interconnect; using it across nodes with ethernet introduces significant latency
- Pipeline parallelism introduces pipeline bubbles (idle time), reducing efficiency
- Both increase deployment complexity and cost
**Staff signal.** Parallelism strategy should match your interconnect topology. Tensor parallelism within a node (NVLink), pipeline parallelism across nodes (ethernet/InfiniBand). Getting this wrong wastes GPU cycles on communication overhead. Most teams should choose models that fit on available hardware rather than engineering multi-GPU serving.

### Inference Server Selection
**What.** Open-source inference servers (vLLM, TensorRT-LLM, TGI, SGLang, and others) provide the runtime for self-hosted model serving. They differ in supported models, optimization techniques, ease of deployment, and performance characteristics.
**Use when.** Choosing infrastructure for self-hosted inference.
**Advantages.**
- Selection criteria: model compatibility, continuous batching support, quantization support, paged attention, multi-GPU parallelism, structured output support, community/maintenance velocity
- Most modern servers support the core optimizations; differentiation is increasingly in ease-of-use and ecosystem integration
**Tradeoffs.**
- The space evolves rapidly; vendor-specific benchmarks are often misleading — run your own workload
- Migration between servers is non-trivial (different APIs, configuration, deployment patterns)
**Staff signal.** Do not over-optimize server selection. Pick one that supports your model, has paged attention and continuous batching, and is actively maintained. Run your actual workload on it and measure. The difference between the top two servers on your real traffic is usually smaller than the difference between a well-tuned and poorly-tuned deployment of either.

## Scaling and Scheduling

### Autoscaling GPU Workloads
**What.** Dynamically adjusting the number of GPU instances serving inference based on demand. Unlike CPU autoscaling, GPU workloads face long cold-start times because model weights must be loaded into GPU memory (seconds to minutes for large models).
**Use when.** Traffic is variable and you want to avoid paying for idle GPUs.
**Advantages.**
- Reduces cost during low-traffic periods
- Warm pools (pre-loaded standby instances) can reduce scale-up latency
**Tradeoffs.**
- Cold start for a large model can be 30–120+ seconds — unacceptable for interactive use if no warm instances are available
- Scale-to-zero saves money but means the first request after silence incurs full cold start
- Queueing during scale-up is necessary; without backpressure, requests time out
**Staff signal.** GPU autoscaling is not like web-server autoscaling. Model load time dominates scale-up latency. Design for it: maintain a warm pool sized to handle baseline traffic + a burst buffer, and queue excess requests with a timeout rather than dropping them. Scale-to-zero is only viable for non-interactive, batch-triggered workloads.

### Capacity Planning and Provisioned Throughput
**What.** Forecasting required tokens/second capacity and deciding between on-demand (pay-per-token, elastic) and provisioned throughput (reserved capacity at a discount, fixed commitment).
**Use when.** Budgeting for inference costs and negotiating with providers or sizing infrastructure.
**Advantages.**
- Provisioned throughput: lower per-token cost (typically 30–60% discount), guaranteed capacity, predictable latency
- On-demand: no commitment, handles burst traffic, lower risk for uncertain workloads
**Tradeoffs.**
- Provisioned: you pay for reserved capacity whether you use it or not; requires accurate demand forecasting
- On-demand: higher per-token cost, subject to rate limits and capacity shortages during peak demand
**Staff signal.** Provision for your P50 traffic, use on-demand for bursts, and queue/defer non-urgent work to fill valleys. This three-tier approach optimizes cost without sacrificing availability for interactive traffic.

### Multi-Tenancy and Fair Scheduling
**What.** When multiple teams, customers, or workloads share GPU infrastructure, a scheduling layer must prevent noisy-neighbour effects where one workload starves others.
**Use when.** Operating shared inference infrastructure for multiple consumers.
**Advantages.**
- Fair scheduling (per-tenant quotas, weighted fair queuing) ensures predictable performance for all tenants
- Higher overall utilization than dedicated-per-tenant provisioning
**Tradeoffs.**
- Scheduling overhead and complexity; quota misconfigurations cause either waste or starvation
- Isolation is imperfect — large requests from one tenant can still impact latency for others within a batch
**Staff signal.** Multi-tenancy on GPUs is harder than CPU multi-tenancy because a single large request can monopolize memory. Use per-tenant request-rate limits, max-context-length limits, and priority classes. Without these, a single customer's runaway agent loop can exhaust shared capacity.

### Priority Lanes: Interactive vs Batch
**What.** Separating inference traffic into priority tiers — interactive (user-facing, latency-sensitive) and batch (background, throughput-sensitive) — with different scheduling and resource allocation.
**Use when.** You have both real-time and background LLM workloads and need to optimize cost without degrading user experience.
**Advantages.**
- Interactive traffic gets low-latency, small-batch processing; batch traffic fills capacity gaps with large batches
- Batch work absorbs the cost of idle capacity that would otherwise be wasted
**Tradeoffs.**
- Requires request classification and routing infrastructure
- Batch work can be preempted or delayed during interactive traffic spikes
**Staff signal.** Priority lanes are the single most effective way to simultaneously improve latency for users and reduce cost for background work. Agent evaluation runs, embedding jobs, and report generation should always be batch-tier, never competing with user-facing inference.

### Batch/Offline Inference
**What.** Processing large datasets through a model asynchronously, maximizing batch size and throughput with no latency constraint.
**Use when.** Evaluation runs, dataset labeling, report generation, embedding entire corpora, or any workload where results are not needed in real time.
**Advantages.**
- 5–10× cheaper per token than interactive inference due to maximum batch sizes and off-peak GPU utilization
- Can use spot/preemptible instances for further cost reduction
**Tradeoffs.**
- Requires job orchestration, checkpointing for long runs, and result storage
- Not suitable for user-facing latency-sensitive requests
**Staff signal.** Teams that run evaluation suites, data labeling, or nightly reports through the same interactive inference endpoint are overpaying by an order of magnitude. Separate these workloads into a batch pipeline with dedicated, throughput-optimized infrastructure.

## Cost Modeling

### Cost Model End-to-End
**What.** A layered cost model: cost per 1k tokens → cost per request (input + output tokens) → cost per task (multiple requests in an agent loop) → cost per user session → cost per monthly active user. Agent loops multiply cost at the task layer because each reasoning step is a separate request.
**Use when.** Budgeting, pricing, and identifying cost hotspots in an LLM-powered product.
**Advantages.**
- Makes cost visible and attributable at every level; prevents surprises at scale
- Exposes the multiplicative effect of agent loops: a 5-step agent with a 4k-token context per step costs 5× a single-call system
**Tradeoffs.**
- Cost models are approximations; actual costs vary with caching, token length variance, and retry rates
- Requires instrumentation to track tokens consumed per task and per user
**Staff signal.** The dangerous line item is agent loops. A 10-step ReAct loop with a 10k-token context costs roughly 100× a single short completion. Set per-task token budgets and instrument cost per user-facing task from day one. Cost overruns in agent systems are rarely linear — they are multiplicative.

### Cost Optimization Levers (Ranked)
**What.** An ordered list of cost-reduction techniques, roughly ranked by ease of implementation and operational simplicity.
**Use when.** Inference cost is the binding constraint and you need to decide where to invest optimization effort.
**Advantages.**
1. **Prompt size reduction** — shorter prompts reduce input token cost directly; simplest lever
2. **Prompt/prefix caching** — reuse computation for shared prefixes; often provider-supported
3. **Model routing** — send simple queries to a cheaper model, hard queries to an expensive one
4. **Capping agent steps** — hard limit on reasoning loop iterations; prevents runaway cost
5. **Batch processing** — move non-urgent work to batch tier at 5–10× lower cost
6. **Quantization** — reduce per-token compute with quality tradeoff
7. **Distillation** — train a smaller model for high-volume, narrow tasks
8. **Model tier selection** — choose the cheapest model that meets quality requirements
**Tradeoffs.**
- Each lever has a quality impact that must be measured; blindly applying all of them degrades the product
- Some levers are mutually exclusive or have diminishing returns when combined
**Staff signal.** Work through this list top-to-bottom. Most teams jump to expensive levers (distillation, self-hosting) before exhausting cheap ones (shorter prompts, caching, step caps). The first three items are often sufficient to cut costs by 40–60%.

## Supporting Infrastructure

### Embedding and Reranking Infrastructure
**What.** Embedding models (bi-encoders for retrieval) and rerankers (cross-encoders for precision) are separate from the generator and serve at much higher volumes with lower per-request cost. They require their own scaling and infrastructure.
**Use when.** Building or operating a RAG system at production scale.
**Advantages.**
- Embedding models are small (roughly 100M–400M parameters) and can run efficiently on CPUs or small GPUs
- Rerankers are moderate-sized and process only top-K candidates; much cheaper than generator inference
- Both can be scaled independently of the generator
**Tradeoffs.**
- Embedding infrastructure must handle corpus-ingestion bursts (re-embedding after updates) alongside query-time embedding
- Batching embeddings is critical for throughput; single-request embedding is wasteful
**Staff signal.** Do not run embedding models on the same GPU instances as your generator. Embedding is high-volume, low-compute; generator inference is lower-volume, high-compute. Co-locating them wastes expensive GPU memory on cheap workloads. Use CPU instances or small dedicated GPUs for embeddings.

### Vector Index Infrastructure
**What.** Vector databases or indexes (HNSW, IVF, DiskANN variants) store and search embedding vectors for RAG retrieval. Operational concerns include memory footprint, index build time, update latency, replication, and sharding.
**Use when.** Sizing and operating the retrieval layer of a RAG system.
**Advantages.**
- In-memory HNSW provides sub-millisecond search at high recall
- On-disk indexes reduce memory cost for very large corpora (hundreds of millions of vectors)
**Tradeoffs.**
- In-memory indexes consume roughly 1–4 KB per vector (depending on dimensionality and overhead) — 100M vectors at 1536 dimensions ≈ 200–600 GB RAM
- Index build and full re-indexing are expensive; incremental updates are supported but may degrade quality over time
- Replication for availability multiplies memory cost
**Staff signal.** Vector index sizing is a memory-planning problem. Before choosing a vector database, estimate: (corpus size × vector dimensionality × bytes per dimension × replication factor). If this exceeds available memory, you need an on-disk index or dimensionality reduction, both of which trade off search quality or latency.

### Latency Budget Decomposition
**What.** Breaking the total time for an agent turn into additive components: network round-trip → queue wait → prefill (prompt processing) → decode (token generation) → tool calls (API latency) → retrieval (embedding + search + reranking). Each component has different optimization levers.
**Use when.** Diagnosing slow agent responses; deciding where to invest optimization effort.
**Advantages.**
- Prevents blind optimization — you invest in the component that actually dominates latency
- Typical interactive agent turn: ~50–200ms network, ~0–2000ms queue, ~200–1000ms prefill, ~500–5000ms decode, ~100–2000ms per tool call
**Tradeoffs.**
- Agent loops multiply the entire budget by the number of steps; a 5-step agent multiplies end-to-end latency by roughly 5× at minimum
- Tool calls (external APIs) are often the dominant latency component and are outside your control
**Staff signal.** Measure before optimizing. Teams often invest in faster inference when the bottleneck is tool-call latency or queue wait time. Instrument every component of the latency budget and optimize the tallest bar first.

### Edge/On-Device Inference
**What.** Running quantized small models directly on user devices (phones, laptops, edge servers) without requiring network connectivity or API calls.
**Use when.** Privacy constraints prohibit sending data to the cloud, offline operation is required, or ultra-low-latency (<50ms) is needed for simple tasks.
**Advantages.**
- Zero network latency; works offline; data never leaves the device
- No per-request cost after initial model deployment
**Tradeoffs.**
- Severely constrained model size (typically <7B parameters quantized to 4-bit); quality ceiling is much lower than cloud-served models
- Device heterogeneity makes deployment and testing complex
- Updates require distributing new model files to all devices
**Staff signal.** Edge inference is viable for classification, simple extraction, and autocomplete — tasks where a small model is sufficient. Do not attempt complex reasoning or multi-step agent workflows on-device; the quality gap is too large. Use edge for the fast path and fall back to cloud for complex requests.

### Inference Observability
**What.** Monitoring metrics specific to inference health: queue depth, batch size, GPU utilization, tokens per second, time-to-first-token (TTFT), inter-token latency, cache hit rate, error rate, and per-tenant consumption.
**Use when.** Operating inference infrastructure in production — which is always.
**Advantages.**
- Queue depth and TTFT are the best leading indicators of capacity problems
- GPU utilization below ~60% indicates under-batching or over-provisioning; above ~90% indicates saturation
- Cache hit rate directly correlates with cost savings from prefix caching
**Tradeoffs.**
- High-cardinality metrics (per-request token counts, per-user costs) are expensive to store and query
- GPU metrics require vendor-specific tooling (NVIDIA DCGM, etc.)
**Staff signal.** The two metrics that matter most operationally are time-to-first-token (TTFT) for user experience and tokens-per-second-per-GPU for cost efficiency. Alert on TTFT p99 degradation (capacity problem) and tokens/sec decline (serving regression). Everything else is diagnostic detail.

## Common interview traps

- **Ignoring KV cache in memory estimates.** Candidates calculate weight memory but forget that KV cache at high concurrency or long context often exceeds weight memory.
- **Assuming linear cost scaling.** Agent loops multiply token cost per task by the number of steps; a 10-step agent is not 10% more expensive than a 1-step call — it is 10×.
- **Conflating throughput and latency.** Larger batches improve throughput but worsen latency; optimizing one without specifying the other is meaningless.
- **Ignoring cold start.** GPU model loading takes 30–120+ seconds for large models; autoscaling does not help if warm pools are not maintained.
- **Treating managed and self-hosted as equivalent.** Managed APIs bundle ops burden into the price; self-hosted cost must include GPU lease, MLOps team, on-call, and security.
- **Over-engineering serving.** Disaggregated prefill/decode and speculative decoding are hyperscaler optimizations; most teams should focus on batching, caching, and model selection.
- **Neglecting embedding infrastructure.** Candidates design generator serving carefully but ignore that embedding throughput bottlenecks degrade the entire RAG pipeline.
- **No cost instrumentation.** If you cannot measure cost per task and cost per user, you cannot optimize or budget.

## Drill questions

1. A 70B-parameter model in FP16 requires ~140 GB of weight memory. Your GPU has 80 GB VRAM. What are your options, and what does each cost you?
2. Your agent takes 8 seconds per turn. Walk through how you would decompose that latency and identify the bottleneck.
3. You serve 10,000 requests per hour through a managed API at $0.01 per 1k input tokens with a 5k-token average prompt. What is the daily cost? How does prompt caching change the economics?
4. When would you choose provisioned throughput over on-demand, and how would you size the provision?
5. A multi-tenant inference cluster serves three teams. One team's agent runs 20-step loops. How do you prevent it from degrading service for the others?
6. Explain why continuous batching matters more than almost any other single serving optimization.
7. Your inference cost per user has doubled over the last month. Walk through how you diagnose the cause.
8. When is self-hosted inference cheaper than managed APIs? What non-cost factors might override the cost comparison?
9. You need to embed 50 million documents. How do you size and schedule this workload?
10. A product manager wants to support 128k context windows. What infrastructure implications does this have?
11. How does speculative decoding improve latency without changing output quality? When does it not help?
12. What metrics would you alert on for a production inference endpoint, and why those specifically?
