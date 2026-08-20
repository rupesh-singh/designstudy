# A10. Model Adaptation: Prompt vs RAG vs Fine-Tune

Models ship with general capabilities, but production systems need specific behaviour — a particular output format, domain vocabulary, cost envelope, or knowledge set. Model adaptation is the engineering discipline of closing the gap between a foundation model's defaults and your product requirements. The cardinal rule is to try the cheapest, most reversible technique first and escalate only when evidence shows it fails. Every step up the adaptation ladder buys capability at the cost of operational burden you will carry for the lifetime of the model.

## Quick reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Adaptation ladder | Escalation path from cheap to expensive techniques | Starting any model-behaviour change; forces cheapest-first thinking |
| Gap-type decision framework | Maps knowledge/format/capability/cost gaps to techniques | You know *what* is wrong but not *how* to fix it |
| Supervised fine-tuning (SFT) | Teaches format, tone, and task structure via examples | Model understands the domain but outputs in the wrong shape |
| LoRA / PEFT | Lightweight fine-tuning that trains <1% of parameters | Need fine-tuning benefits without full-model cost |
| Full fine-tuning vs PEFT | When to pay for updating all weights | LoRA plateaus on a complex capability change |
| Preference tuning (RLHF/DPO) | Aligns outputs to human preference rankings | You can rank outputs but can't write gold answers |
| Distillation | Large model teaches a smaller one | Proven quality at high cost; need to cut per-request cost |
| Quantization | Reduced-precision weights for cheaper serving | Serving cost or latency is the bottleneck, not quality |
| Training data curation | Quality/quantity of adaptation data | Planning any fine-tuning run |
| Catastrophic forgetting | Regression on untrained tasks after adaptation | Evaluating a fine-tuned model before deployment |
| Evaluation before/after | Held-out test sets to measure real impact | Every adaptation attempt, no exceptions |
| Operational cost of ownership | Ongoing burden of maintaining a fine-tuned model | Making the build-vs-buy decision for adaptation |
| Fine-tune vs long context vs RAG | Direct comparison for domain knowledge | Deciding how to inject proprietary knowledge |
| When fine-tuning genuinely wins | Narrow conditions that justify the cost | Validating that fine-tuning is actually the right call |
| Embedding model fine-tuning | Adapting retrieval, not generation | RAG quality is poor despite good generator |
| Reranker training | Cheaper retrieval quality lever | Recall is fine but precision/ranking is poor |
| Prompt optimization | Automated prompt search as a fine-tuning alternative | Want fine-tuning-level gains without training |
| Model bake-off harness | Systematic model selection and benchmarking | Choosing between candidate models for a task |
| Open-weight vs proprietary | Control/compliance/cost/capability tradeoffs | Architectural model selection |
| Model deprecation and portability | Avoiding lock-in to one model's quirks | Building systems that survive model transitions |

## The Adaptation Spectrum

### The Adaptation Ladder
**What.** A ranked sequence of techniques — system prompt → few-shot examples → retrieval-augmented generation → supervised fine-tuning → continued pretraining — ordered by increasing cost, time-to-deploy, and operational burden. Always start at the cheapest rung and climb only when measurement shows the current rung is insufficient.
**Use when.** Starting any project to change model behaviour. Forces the team to attempt prompt engineering and RAG before committing to training infrastructure.
**Advantages.**
- Prompt changes deploy in minutes, fine-tuning takes days to weeks; the ladder keeps iteration speed high
- Lower rungs are reversible and compose easily; higher rungs create ongoing maintenance obligations
- Each rung produces evaluation data that informs the next, so you climb with evidence rather than intuition
**Tradeoffs.**
- Teams under pressure skip rungs and jump to fine-tuning prematurely, wasting GPU budget on a problem a better prompt would have solved
- The ladder is not always strictly ordered — some problems (e.g., output format compliance at >99% reliability) jump directly to SFT
**Staff signal.** The ladder is not just about money; it is about *blast radius*. A prompt change affects one deployment. A fine-tuned model is a new artifact with its own lifecycle, regression surface, and deprecation schedule. The operational cost often exceeds the training cost within months.

### The Decision Framework: What Type of Gap Are You Closing?
**What.** A diagnostic that classifies the gap between current model output and desired behaviour into four categories — *knowledge* (model lacks facts), *format/style* (model knows the answer but presents it wrong), *capability* (model cannot perform the reasoning), or *cost* (model can do it but is too expensive/slow) — and maps each to the appropriate technique.
**Use when.** You have evidence that the model is underperforming but need to decide where to invest engineering effort.
**Advantages.**
- Knowledge gap → RAG or tool use; avoids fine-tuning on facts that will go stale
- Format/style gap → few-shot prompting or SFT; fast turnaround
- Capability gap → larger/better model, fine-tuning on reasoning chains, or continued pretraining
- Cost gap → distillation, quantization, caching, or model routing
**Tradeoffs.**
- Real production gaps are often mixed; you may need prompt + RAG + SFT together
- Misdiagnosis (treating a knowledge gap as a capability gap) wastes months of fine-tuning effort
**Staff signal.** Before any adaptation work, build a small diagnostic eval set that isolates the gap type. Tag failures as knowledge/format/capability/cost. This tag distribution is the single most important input to your adaptation strategy.

## Fine-Tuning Techniques

### Supervised Fine-Tuning (SFT)
**What.** Training a model on (input, desired-output) pairs to shift its distribution toward a specific format, tone, or task structure. Conceptually, it adjusts weights so the model preferentially produces outputs that look like your examples.
**Use when.** The model understands the domain (it can answer correctly when coached heavily in the prompt) but fails on format compliance, consistent tone, or structured output reliability at high volumes.
**Advantages.**
- Dramatically improves output format consistency (e.g., always valid JSON, always following a schema)
- Reduces prompt length by baking instructions into weights, cutting per-request token cost
- Can make a smaller model match a larger model on a narrow task, saving inference cost
**Tradeoffs.**
- Requires hundreds to low thousands of high-quality examples; data creation dominates project time
- Poor at injecting new factual knowledge — facts learned via fine-tuning are brittle and hard to update
- Creates a model artifact you must version, store, evaluate, and eventually retrain
**Staff signal.** SFT compresses your prompt into weights. If your system prompt is long and repetitive across requests, SFT pays for itself in reduced token cost alone — do the arithmetic before deciding.

### LoRA and Parameter-Efficient Fine-Tuning (PEFT)
**What.** Techniques that freeze most model parameters and train small adapter matrices (LoRA trains low-rank decompositions injected at attention layers, typically <1% of total parameters). The adapter is a separate artifact that is loaded alongside the base model at serving time.
**Use when.** You need fine-tuning benefits but cannot afford full-model training cost, or you need to serve multiple task-specific variants from the same base model (multi-tenant serving).
**Advantages.**
- Training cost is roughly 5–10× cheaper than full fine-tuning in GPU-hours
- Adapter files are small (tens to hundreds of MB vs tens of GB for full checkpoints), enabling fast swapping
- Multiple LoRA adapters can share one base model in memory, enabling multi-tenant serving with per-customer behaviour
**Tradeoffs.**
- Quality ceiling: LoRA adapters may not match full fine-tuning on complex capability shifts because they constrain the update rank
- Adapter management adds serving complexity — routing requests to the correct adapter, versioning, A/B testing
- Merging adapters into the base model is possible but can degrade quality compared to live adapter serving
**Staff signal.** LoRA's operational superpower is multi-tenancy. One GPU cluster serves one base model with dozens of customer-specific adapters hot-swapped per request. This architecture is the cost-efficient answer to "every customer wants a custom model."

### Full Fine-Tuning vs PEFT
**What.** Full fine-tuning updates every parameter; PEFT methods update a small subset. The choice determines training cost, infrastructure requirements, and serving architecture.
**Use when.** Deciding whether LoRA/PEFT is sufficient or whether you must accept the cost of full fine-tuning.
**Advantages.**
- Full fine-tuning has the highest expressiveness ceiling — the model can change any internal representation
- Justified when the adaptation requires deep capability changes (new language, new reasoning pattern) or when you will serve only one variant
**Tradeoffs.**
- Full fine-tuning costs 5–10× more in compute, produces a complete model checkpoint (storage, distribution), and makes multi-tenant serving expensive
- Re-basing onto a new foundation model version requires re-running the full training; with PEFT, you may only need to re-train the adapter
**Staff signal.** The real cost of full fine-tuning is not the training run — it is that you now own a diverged fork of the base model. Every upstream improvement requires you to re-merge, re-evaluate, and re-deploy. Budget for this operational tax before committing.

### Preference Tuning (RLHF / DPO-Style)
**What.** A second stage of fine-tuning where the model learns from *ranked* outputs (preferred vs dispreferred) rather than single gold answers. RLHF uses a reward model and RL optimization; DPO collapses this into a simpler direct optimization objective.
**Use when.** You can easily rank outputs as better/worse but cannot write a single correct answer — common for style, helpfulness, safety, and open-ended tasks.
**Advantages.**
- Captures nuanced human preferences that are hard to specify in demonstrations alone
- Effective for reducing harmful or off-brand outputs
**Tradeoffs.**
- Requires substantial human annotation of preference pairs (expensive, slow)
- Reward hacking: the model learns to game the reward signal rather than genuinely improving
- Most product teams should not attempt this — it is a capability of model providers, not application builders
**Staff signal.** If you find yourself considering preference tuning, first ask whether you can solve the problem by filtering outputs with a classifier or rewriting with a second LLM call. These are operationally simpler and achieve 80% of the value.

### Distillation
**What.** Using a large, capable (teacher) model to generate training data or soft targets that a smaller, cheaper (student) model learns from. The student inherits a portion of the teacher's quality at a fraction of the serving cost.
**Use when.** You have proven quality with an expensive model and need to reduce per-request cost for high-volume production use.
**Advantages.**
- Can produce a small model that approaches the large model's quality on a narrow task at 5–20× lower inference cost
- Training data is cheap to generate — the teacher produces it programmatically
**Tradeoffs.**
- Quality ceiling: the student is bounded by the teacher's performance and typically loses 5–15% on hard cases
- Legal/license considerations — some model providers prohibit using their outputs to train competing models
- You inherit the teacher's biases and failure modes, often without visibility
**Staff signal.** Distillation is the first technique to consider when your cost model shows the current model is too expensive at scale. Build the pipeline: teacher generates → human spot-checks a sample → student trains → eval compares. This loop should be repeatable, not a one-off.

### Quantization
**What.** Reducing the numerical precision of model weights (e.g., from FP16 to INT8 or INT4), which shrinks memory footprint and increases inference throughput at the cost of small quality degradation.
**Use when.** Serving cost or latency is the binding constraint, and you have verified that quality degradation on your task is acceptable.
**Advantages.**
- INT8 quantization roughly halves memory, allowing a model to fit on fewer/smaller GPUs
- INT4 can roughly quarter memory; combined with efficient kernels, can double throughput
- Often composable with other optimizations (batching, caching)
**Tradeoffs.**
- Quality degradation varies by model and task; must be measured, not assumed
- Some quantization methods require calibration data; others are post-training and approximate
- Debugging quality regressions in quantized models is harder — errors are diffuse, not localized
**Staff signal.** Quantization is a serving-team decision, not a modelling decision. Treat it like a compiler optimization: measure before and after on your eval set, and gate deployment on a quality threshold. Never quantize without task-specific evaluation.

## Data and Evaluation

### Training Data Curation
**What.** The process of assembling, cleaning, deduplicating, and labeling the dataset used for any fine-tuning. Data quality dominates fine-tuning outcomes more than model size, hyperparameters, or technique choice.
**Use when.** Planning any fine-tuning effort.
**Advantages.**
- A few hundred high-quality, diverse examples often outperform thousands of noisy ones
- Deduplication prevents the model from memorizing repeated patterns and overfitting
- Intentional diversity in examples improves generalization to production distribution
**Tradeoffs.**
- Expert labeling is expensive and slow; synthetic data generation is cheap but risks distribution narrowing
- Synthetic data generated from the same model family can cause model collapse — progressive quality degradation across training generations
- Label quality is hard to audit at scale; systematic labeler biases propagate into model behaviour
**Staff signal.** Budget more time for data curation than for training. The ratio should be roughly 3:1 (data:training). A well-curated dataset of 500 examples often beats a hastily assembled set of 5,000.

### Catastrophic Forgetting
**What.** After fine-tuning on a narrow task, the model degrades on tasks it previously handled well. The new training distribution overwrites representations the model relied on for general capabilities.
**Use when.** Evaluating any fine-tuned model — forgetting is the default outcome unless mitigated.
**Advantages.**
- Awareness drives proper evaluation: test the fine-tuned model on a broad suite, not just the target task
- Mitigation techniques include mixing general-purpose data into the fine-tuning set and using PEFT (which modifies fewer parameters)
**Tradeoffs.**
- Detecting forgetting requires maintaining evaluation suites for capabilities you care about but did not train on
- There is a fundamental tension between specialization (high target-task performance) and generalization
**Staff signal.** Maintain a "regression suite" of diverse tasks that must not degrade. Gate every fine-tuned model deployment on passing this suite. This is the fine-tuning equivalent of a CI test suite, and skipping it is how teams ship models that break production.

### Evaluation Before and After Adaptation
**What.** Measuring model performance on a held-out test set that was never used during prompt development or training. The only reliable way to know whether an adaptation actually helped.
**Use when.** Every single adaptation attempt, whether prompt change, RAG addition, or fine-tuning.
**Advantages.**
- Prevents confirmation bias ("it seems better on my examples")
- Enables apples-to-apples comparison across techniques and model versions
**Tradeoffs.**
- Building a representative eval set requires upfront investment; teams skip it and regret it later
- Eval metrics must be chosen carefully — BLEU/ROUGE are poor proxies for real quality on most LLM tasks; prefer task-specific metrics or LLM-as-judge with calibration
**Staff signal.** "It looks better" is not evidence. Ship with an eval set, a metric, and a threshold. If the adaptation does not move the metric above the threshold on the held-out set, it does not ship. This discipline separates professional adaptation from tinkering.

## Operational Considerations

### Operational Cost of Owning a Fine-Tuned Model
**What.** The ongoing engineering burden of maintaining a custom model: retraining cadence, base-model deprecation tracking, evaluation suite maintenance, GPU provisioning for training, artifact storage, and reproducibility infrastructure.
**Use when.** Making the decision to fine-tune; the total cost is dominated by operations, not the initial training run.
**Advantages.**
- Explicit cost accounting prevents teams from underestimating the true cost of fine-tuning
**Tradeoffs.**
- Base model providers deprecate versions; your fine-tune is pinned to a snapshot that will eventually lose support
- Retraining when data or requirements change requires maintaining the full pipeline (data, training, eval, deployment)
- Reproducibility requires version-controlling data, hyperparameters, and base model — an MLOps problem
**Staff signal.** Before fine-tuning, answer: who retrains this model in 6 months when the base model is deprecated? If the answer is "nobody" or "we'll figure it out," you are creating technical debt, not a solution.

### Fine-Tuning vs Long Context vs RAG for Domain Knowledge
**What.** Three competing approaches to injecting proprietary knowledge: fine-tuning bakes it into weights; long context stuffs it into the prompt; RAG retrieves relevant subsets dynamically.
**Use when.** Deciding how to make a model knowledgeable about your domain.
**Advantages.**
- RAG: knowledge stays fresh (update the index, not the model), scales to large corpora, attributable
- Long context: simple implementation (just concatenate), no retrieval pipeline to build
- Fine-tuning: lowest per-request latency (no retrieval step), works offline
**Tradeoffs.**
- Fine-tuning is worst at freshness and worst at factual reliability — facts in weights are unverifiable and un-updatable
- Long context is expensive per request (all tokens are processed) and degrades on very long inputs (lost-in-the-middle)
- RAG requires a retrieval pipeline (chunking, embedding, indexing, reranking) with its own failure modes
**Staff signal.** For domain knowledge, the default answer is RAG. Fine-tuning teaches the model *how* to use domain knowledge (vocabulary, reasoning patterns), not the facts themselves. Combine RAG for facts with SFT for format/style — this is the high-ROI combination most teams miss.

### When Fine-Tuning Genuinely Wins
**What.** The narrow set of conditions where fine-tuning is the correct engineering choice despite its operational cost.
**Use when.** Validating that your situation actually justifies fine-tuning rather than simpler alternatives.
**Advantages.**
- High-volume, narrow task: amortize training cost over millions of requests where per-request savings compound
- Strict latency/cost target: SFT on a small model beats prompting a large model when you need <100ms inference
- Proprietary format/style: consistent output structure that prompting achieves at 90% but you need 99%+
- Offline/edge deployment: model must run without API access; fine-tuned small models fit on-device
**Tradeoffs.**
- If any of the above conditions are absent, the operational burden usually exceeds the benefit
**Staff signal.** Fine-tuning is a production optimization, not a development tool. Prove the approach works with prompting or RAG first, measure the gap, and fine-tune to close it. Never fine-tune as the first step.

## Retrieval-Side Adaptation

### Embedding Model Fine-Tuning
**What.** Adapting the embedding model used in RAG retrieval to your domain's vocabulary, terminology, and relevance criteria. Often delivers higher ROI than fine-tuning the generator because retrieval quality is the bottleneck in most RAG systems.
**Use when.** RAG retrieval recall or precision is poor despite good chunking and indexing — the embedding model does not understand your domain's semantic similarity.
**Advantages.**
- Domain-specific embeddings dramatically improve retrieval hit rates for specialized vocabularies
- Embedding models are small (roughly 100M–400M parameters); fine-tuning is fast and cheap relative to generator fine-tuning
- Improved retrieval directly improves generation quality downstream
**Tradeoffs.**
- Requires training data in the form of (query, relevant-document) pairs — often derived from user click logs or expert annotation
- Re-embedding the entire corpus after fine-tuning is a batch job that scales with corpus size
**Staff signal.** When RAG quality is poor, teams instinctively reach for generator fine-tuning. Almost always, fine-tuning the embedding model or adding a reranker has higher marginal return. Diagnose retrieval quality independently before touching the generator.

### Reranker Training
**What.** Training a cross-encoder reranker that scores (query, document) pairs more accurately than the embedding model's dot-product similarity. Operates on the top-K retrieved results, re-ordering them before they reach the generator.
**Use when.** Retrieval recall is acceptable (the right documents appear in top-50) but precision in top-5 is poor.
**Advantages.**
- Cross-encoders are more accurate than bi-encoders because they attend to query and document jointly
- Reranker fine-tuning is cheaper than generator fine-tuning and requires less data
- Modular: swap rerankers without changing the rest of the pipeline
**Tradeoffs.**
- Adds latency (each candidate must be scored individually); practical limit is roughly 50–200 candidates
- Another model to train, version, and deploy
**Staff signal.** Reranker training is often the single highest-ROI adaptation in a RAG system. It is cheaper than embedding fine-tuning (no re-indexing) and cheaper than generator fine-tuning, yet directly improves the quality of context the generator sees.

## Alternatives to Fine-Tuning

### Prompt Optimization / Automated Prompt Search
**What.** Systematic or automated methods for finding the best prompt — grid search over prompt variations, LLM-generated prompt candidates evaluated against a test set, or gradient-free optimization techniques (e.g., DSPy-style optimizers).
**Use when.** You want fine-tuning-level improvements but cannot afford training infrastructure or operational burden.
**Advantages.**
- No training infrastructure required; changes deploy instantly
- Composable with RAG, tool use, and other prompt-level techniques
- Can match SFT on some tasks when the base model is capable enough
**Tradeoffs.**
- Optimized prompts are fragile — they may overfit to the eval set or break when the model version changes
- Search space is large; automated methods require many eval-set queries (cost)
**Staff signal.** Prompt optimization is the under-explored middle ground. Before committing to fine-tuning, run an automated prompt search against your eval set. If it closes most of the gap, you avoid the entire operational burden of model ownership.

### Model Bake-Off Harness
**What.** A standardized evaluation pipeline that runs your task-specific test set against multiple candidate models, producing comparable metrics (quality, latency, cost, format compliance) to inform model selection.
**Use when.** Choosing between candidate models — different providers, sizes, or fine-tuned variants.
**Advantages.**
- Removes opinion from model selection; decisions are data-driven
- Reusable across model upgrades and new model releases
- Exposes cost/quality Pareto frontier, enabling informed tradeoffs
**Tradeoffs.**
- Requires investment in a representative eval set and automated scoring (LLM-judge or task-specific metrics)
- Results are only as good as the eval set's coverage of production distribution
**Staff signal.** Build the bake-off harness before your first model selection and maintain it permanently. It pays dividends every time a new model releases, a provider changes pricing, or your task requirements shift. The harness is a capital asset.

### Open-Weight vs Proprietary Models
**What.** Open-weight models (e.g., Llama, Mistral, Qwen families) provide downloadable weights you can host and modify; proprietary models (e.g., GPT, Claude families) are accessible only via API.
**Use when.** Making the foundational model selection for a product.
**Advantages.**
- Open-weight: full control over serving, data residency, fine-tuning, and cost at scale; no per-token API fees
- Proprietary: higher capability ceiling on many tasks; zero infrastructure burden; rapid improvement cadence from provider
**Tradeoffs.**
- Open-weight: you own the infrastructure, security, and ops burden; capability may lag proprietary frontier models
- Proprietary: vendor lock-in, data governance concerns, rate limits, pricing changes, model deprecation outside your control
**Staff signal.** The open-vs-proprietary decision is really about who carries the ops burden and who controls the deprecation timeline. At low volume, proprietary wins on total cost. At high volume with stable tasks, open-weight wins. The crossover point depends on your infrastructure team's maturity.

### Model Deprecation and Portability
**What.** Models are deprecated by providers (API models) or superseded by better releases (open-weight). Systems tightly coupled to a specific model's output distribution, token limits, or quirks are fragile.
**Use when.** Designing any system that depends on an LLM — which is every system in this reference.
**Advantages.**
- Portability-oriented design (structured outputs, model-agnostic prompts, eval harnesses) reduces switching cost
- Abstracting the model behind a consistent interface enables A/B testing and gradual migration
**Tradeoffs.**
- Perfect model abstraction is impossible — different models have different strengths, and prompts that work well on one may underperform on another
- Maintaining compatibility across models adds testing burden
**Staff signal.** Design for model replacement from day one. Pin model versions in config, maintain an eval harness, and avoid relying on undocumented model behaviours. The model you ship with today will not be the model you are running in 12 months.

## Common interview traps

- **Jumping to fine-tuning for a knowledge gap.** Fine-tuning bakes static facts into weights — they cannot be updated or cited. RAG is almost always the right answer for knowledge.
- **Ignoring prompt engineering before fine-tuning.** Many tasks are solvable with better prompts and few-shot examples; fine-tuning adds permanent operational cost.
- **Confusing LoRA with full fine-tuning in capability.** LoRA is powerful but has an expressiveness ceiling; claiming it always matches full fine-tuning is inaccurate.
- **Forgetting catastrophic forgetting.** Candidates describe fine-tuning benefits without mentioning regression testing on non-target tasks.
- **Treating quantization as free.** Quality degradation is task-dependent and must be measured, not assumed away.
- **Overlooking embedding fine-tuning.** When RAG quality is poor, candidates default to generator fine-tuning when the retrieval model is the actual bottleneck.
- **Underestimating operational cost.** Training cost is a one-time expense; model maintenance is ongoing. Candidates cite GPU-hours but ignore retraining cadence, base-model deprecation, and eval suite upkeep.
- **No eval set.** Any adaptation without a held-out evaluation is an anecdote, not engineering.

## Drill questions

1. Your RAG system retrieves relevant documents but the generator's answers are poorly formatted. Would you fine-tune the generator, the embedding model, or try something else first? Why?
2. A team wants to fine-tune a model on 50 examples. What concerns would you raise, and what alternatives would you suggest?
3. You fine-tuned a model for customer support and quality improved — but now it fails at summarization, which it previously handled well. What happened and how do you prevent this?
4. A high-volume API endpoint uses GPT-4-class quality but costs $0.15 per request. Walk through the cost-reduction options in order of operational simplicity.
5. When would you choose full fine-tuning over LoRA, and what ongoing cost does that choice create?
6. Your team fine-tuned a model 6 months ago. The base model provider just deprecated that version. What happens next, and how would you have designed the system differently?
7. How do you decide whether poor RAG performance is a retrieval problem or a generation problem? What do you measure?
8. A colleague proposes using synthetic data from GPT-4 to fine-tune a smaller model. What are the risks, and how would you mitigate them?
9. You need the model to always output valid JSON matching a specific schema. Compare prompt engineering, constrained decoding, and SFT as solutions.
10. When would preference tuning (RLHF/DPO) be worth the investment for a product team vs simply filtering outputs with a classifier?
11. Two candidate models score similarly on your eval set but one is open-weight and the other is proprietary. What factors beyond benchmark scores drive your decision?
12. How would you build a model bake-off harness that remains useful across multiple model generations?
