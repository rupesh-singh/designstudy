# A7. Evaluation & Experimentation

You cannot ship what you cannot measure, and LLM-powered systems have no unit tests by default. A function that returns a different answer each time, where multiple answers may all be acceptable, breaks every assumption behind traditional QA. This file covers how to build the evaluation muscle that turns agentic AI from demo to production: metrics that matter, statistical discipline to trust them, and the feedback loops that compound quality over time. Mastery here is the single strongest differentiator between candidates who have shipped agents and those who have only prototyped them.

## Quick-reference table

| Concept | One-line role | Reach for it when |
|---|---|---|
| Why traditional testing breaks | Explains non-determinism and semantic equivalence | Justifying eval investment to stakeholders |
| Eval-driven development | Build the eval before the feature | Starting any prompt/tool/agent change |
| Golden datasets | Curated input–output pairs as ground truth | You need offline quality measurement |
| Offline vs online vs shadow eval | Three evaluation stages with different fidelity | Deciding when and where to measure |
| Outcome vs trajectory eval | Final-answer correctness vs step-level reasoning | Agents with multi-step plans |
| Tool-call accuracy | Did the agent call the right tool with the right args | Any tool-using agent |
| Task completion & cost metrics | Commercial success metrics | Justifying agent ROI |
| Deterministic assertions | Hard checks that need no LLM judge | Schema, citation, format validation |
| LLM-as-judge | Use a model to grade another model's output | Semantic quality at scale |
| LLM-as-judge failure modes | Position bias, verbosity bias, self-preference | Designing trustworthy auto-eval |
| Human evaluation | Gold-standard but expensive labeling | Calibrating automated metrics |
| Statistical rigor | Sample size, variance, confidence intervals | Trusting any eval result |
| Regression suites & CI gates | Automated quality gates on changes | Prompt/model change management |
| RAG component-level eval | Separate retrieval from generation metrics | Localizing RAG failures |
| Failure taxonomy | Cluster, categorize, prioritize errors | Systematic quality improvement |
| Benchmarks vs your task | Public scores ≠ production quality | Model selection |
| Online metrics | User satisfaction and behavioral signals | Measuring real-world quality |
| A/B testing agents | Controlled experiments with long feedback loops | Comparing agent variants |
| Canary & staged rollout | Incremental deployment of model/prompt changes | Risk-managed releases |
| Silent regression | Provider-side model updates break your system | Ongoing model governance |
| Cost & latency as eval dimensions | Treat efficiency as a quality metric | Budget-constrained systems |
| Safety evals & red-teaming | Adversarial testing as a distinct eval suite | Pre-launch and recurring safety checks |
| Eval flywheel | Mine production traces into test cases | Compounding quality over time |

## The evaluation problem

### Why traditional testing breaks down
**What.** LLM outputs are non-deterministic (even at temperature 0, quantization and batching introduce variance), there is rarely a single correct answer, and semantically equivalent outputs can have wildly different surface forms. This means assert-equals style testing is fundamentally insufficient.
**Use when.** You need to explain to a team why "just write unit tests" does not work for prompt-based features, or why a passing test suite does not guarantee quality.
**Advantages.**
- Forces the team to adopt probabilistic, metric-based quality frameworks early
- Prevents false confidence from a handful of cherry-picked examples
**Tradeoffs.**
- Evaluation infrastructure becomes a first-class system to build and maintain
- Cultural shift: engineers accustomed to green/red CI must learn to reason about distributions
**Staff signal.** The non-determinism is not just temperature — model providers silently update weights, quantization, and serving infrastructure. Your eval suite is the only thing that detects these changes, which makes it a monitoring system as much as a test suite.

### Eval-driven development
**What.** The practice of writing the evaluation dataset and metric before changing a prompt, tool, or agent. Analogous to TDD: define what "better" means first, then iterate until the metric improves without regressing other metrics.
**Use when.** Any prompt, tool configuration, or model change — no exceptions. Without a pre-defined eval, you are judging quality by vibes.
**Advantages.**
- Prevents the "it looks better on my three examples" trap
- Creates an artifact (the eval set) that accumulates value across the project
**Tradeoffs.**
- Upfront cost: building a good eval set for a new feature can take days
- Risk of Goodharting: optimizing for the eval metric rather than real user value
**Staff signal.** The eval set is not static — schedule quarterly reviews to retire stale examples and add fresh production-sourced ones. An eval set that never changes will eventually measure your ability to overfit, not your quality.

## Datasets and measurement

### Golden / reference datasets
**What.** Curated sets of (input, expected-output) or (input, acceptable-outputs) pairs that serve as ground truth for offline evaluation. Sourcing includes production logs (with PII stripped), hand-authored examples, adversarial cases, and edge cases discovered during incidents.
**Use when.** You need repeatable, offline quality measurement. Even 50–100 high-quality examples per capability are far more valuable than 10,000 noisy ones.
**Advantages.**
- Enables fast iteration without production traffic
- Can encode rare but critical failure modes that would take months to encounter organically
**Tradeoffs.**
- Curation is expensive; label quality degrades if rushed
- Test-set contamination: if golden examples leak into few-shot prompts or fine-tuning data, eval scores become meaningless
- Staleness: real user behavior drifts; a static dataset becomes unrepresentative
**Staff signal.** Partition your golden set into a dev-eval set (used during development, acceptable to overfit slightly) and a held-out test set (touched only for release decisions). Treat the held-out set like a production secret — once contaminated, it cannot be trusted again.

### Offline eval vs online eval vs shadow evaluation
**What.** Offline eval runs on stored datasets before deployment. Online eval measures live traffic with real users. Shadow (or dark-launch) eval runs the new system in parallel on live traffic without exposing results to users, comparing outputs offline.
**Use when.** Offline for fast iteration, shadow for safe validation on real distribution, online for measuring actual user impact.
**Advantages.**
- Offline: fast, cheap, repeatable. Shadow: real traffic distribution without user risk. Online: ground truth of user satisfaction.
**Tradeoffs.**
- Offline misses distribution shift. Shadow doubles compute cost. Online risks user-facing regressions.
- Shadow evaluation cannot measure interactive effects (user follow-ups depend on the response they actually saw)
**Staff signal.** Shadow eval is most valuable when your offline eval set is small or stale. It lets you gauge real-distribution performance before committing. Budget the 2× compute cost as an insurance premium.

## Agent-specific metrics

### Outcome eval vs trajectory eval
**What.** Outcome eval checks if the final answer is correct. Trajectory eval checks whether the agent took the right steps in the right order — correct tool selections, reasonable intermediate reasoning, no unnecessary detours. Agents need both because a correct final answer reached via an unsafe or wasteful path is still a problem.
**Use when.** Any multi-step agent. Outcome-only eval misses agents that stumble into correct answers by brute force (expensive, fragile) or that take dangerous intermediate actions.
**Advantages.**
- Trajectory eval catches inefficiency, unsafe tool use, and hallucinated intermediate steps even when the final answer happens to be correct
- Enables debugging: you can pinpoint which step went wrong
**Tradeoffs.**
- Trajectory eval requires defining "correct" sequences, which may be ambiguous when multiple valid paths exist
- More complex annotation: labelers need domain expertise to judge intermediate steps
**Staff signal.** Weight trajectory eval more heavily for agents with side effects (writes, API calls, emails). For read-only agents, outcome eval may suffice. The key question is: "If the agent got the right answer by accident, would the path it took have caused harm?"

### Tool-call accuracy
**What.** Measures whether the agent selected the correct tool, passed the correct arguments, called tools in a valid order, and avoided unnecessary calls. Broken into sub-metrics: tool selection precision/recall, argument correctness, call sequence validity, and redundant-call rate.
**Use when.** Evaluating any tool-using agent. A wrong tool call with correct-looking output is worse than an obvious failure because it is silently wrong.
**Advantages.**
- Catches subtle bugs like calling a write API when a read was intended, or passing user-A's ID into user-B's query
- Redundant-call rate directly maps to cost and latency
**Tradeoffs.**
- Requires ground-truth tool-call sequences, which are expensive to annotate
- Multiple valid tool orderings make exact-match scoring too strict; you need a more flexible matcher
**Staff signal.** Track the "unnecessary tool call" rate as a cost metric. Agents frequently make exploratory calls that add latency and expense. A 20% reduction in unnecessary calls can matter more than optimizing prompt tokens.

### Task completion rate and cost per successful task
**What.** Task completion rate is the fraction of user tasks the agent resolves without human escalation. Cost per successful task is total spend (tokens, tool invocations, compute) divided by successful completions — the metric that actually matters commercially.
**Use when.** Reporting agent ROI to leadership or comparing agent architectures.
**Advantages.**
- Directly ties to business value; a fast, cheap agent that fails 60% of the time may cost more than a slow, expensive one that succeeds 95% of the time
- Forces you to account for the cost of failures (retries, human fallback)
**Tradeoffs.**
- Defining "successful completion" is hard for open-ended tasks
- Must include the cost of failed attempts, not just successful ones
**Staff signal.** Always report cost per *successful* task, not cost per attempt. This single metric reveals whether your agent is economically viable and whether optimizing for speed or accuracy yields more ROI.

## Evaluation methods

### Deterministic assertions
**What.** Hard-coded checks that require no LLM judge: output matches a JSON schema, contains a required citation, ran the expected SQL query, returned a value within a known range, or produced valid code that compiles. These are the cheapest, fastest, and most reliable eval signals.
**Use when.** Any time a portion of the output has a verifiable structural or factual constraint. Layer these beneath LLM-as-judge for defense in depth.
**Advantages.**
- Zero cost, millisecond execution, no false positives if well-designed
- Can run in CI on every commit
**Tradeoffs.**
- Cannot assess semantic quality, fluency, or helpfulness
- Brittle if over-specified (e.g., asserting exact wording instead of meaning)
**Staff signal.** Maximize the surface covered by deterministic checks before reaching for LLM-as-judge. Every check you can express as code is one fewer flaky, expensive model call in your eval pipeline.

### LLM-as-judge
**What.** Using a (typically stronger) LLM to score another model's output against a rubric. Can be pointwise (rate this output 1–5 on helpfulness) or pairwise (which of output A and B is better). Requires a carefully designed rubric with criteria definitions and anchor examples.
**Use when.** You need to evaluate semantic quality — correctness, helpfulness, safety, tone — at scale, and human annotation is too slow or expensive for your iteration speed.
**Advantages.**
- 10–100× cheaper than human annotation; enables eval on thousands of examples per day
- Correlates well with human judgments when properly calibrated (typically 80–90% agreement on binary good/bad)
**Tradeoffs.**
- The judge itself can be wrong, biased, or inconsistent
- Requires calibration against human labels; cannot be trusted without ground-truth validation
- Adds model-call cost and latency to your eval pipeline
**Staff signal.** Always calibrate your LLM-judge against a set of human-labeled examples before trusting it. Report the judge-human agreement rate alongside your eval scores. If agreement is below 80%, your rubric needs refinement, not more examples.

### LLM-as-judge biases and failure modes
**What.** Known systematic errors: position bias (preferring the first or last option in pairwise comparisons), verbosity bias (longer answers score higher regardless of correctness), self-preference (a model rates its own outputs higher), and judge drift (judge behavior changes when the underlying model is updated by the provider).
**Use when.** Designing or auditing an LLM-based evaluation pipeline.
**Advantages.**
- Awareness enables mitigations: randomize position, normalize for length, use a different model family as judge, re-calibrate regularly
**Tradeoffs.**
- Mitigations add complexity and cost (e.g., running each pairwise comparison twice with swapped positions doubles eval cost)
**Staff signal.** Judge drift is the most underappreciated risk. If your judge model is updated by its provider, your eval scores shift even though your system has not changed. Pin your judge model version, and re-calibrate when you upgrade it — treat judge upgrades as their own release event.

### Human evaluation and annotation
**What.** Domain experts or trained annotators rate model outputs against guidelines. Inter-annotator agreement (e.g., Cohen's kappa, Krippendorff's alpha) measures label reliability.
**Use when.** Calibrating LLM-as-judge, evaluating subjective quality, building golden datasets, and validating high-stakes outputs.
**Advantages.**
- Gold standard for subjective quality; the only ground truth for ambiguous tasks
- Catches failure modes that automated metrics miss
**Tradeoffs.**
- Expensive, slow, does not scale to continuous eval
- Annotator quality varies; without clear guidelines and agreement metrics, labels are noisy
**Staff signal.** If your inter-annotator agreement is low (kappa < 0.6), the task definition is ambiguous — fixing the annotation guidelines will improve quality more than collecting more labels. Invest in the rubric, not the volume.

### Statistical rigor
**What.** Eval results are random variables. Non-deterministic outputs mean you must run each example multiple times, compute confidence intervals, and ensure adequate sample sizes before drawing conclusions. A 3-example demo proves nothing; even 100 examples with a single run each may be unreliable for small effect sizes.
**Use when.** Any time you report an eval score or compare two system variants.
**Advantages.**
- Prevents shipping regressions masked by variance
- Enables principled A/B decisions
**Tradeoffs.**
- Multiple runs per example multiply eval cost (3–5 runs is typical)
- Larger sample sizes delay iteration
**Staff signal.** For agents, variance is higher than for single-turn completions because each step compounds randomness. Budget for at least 3 runs per example and report the interquartile range alongside the mean. If the IQR overlaps between two variants, you do not have a statistically meaningful difference.

## Eval infrastructure

### Regression suites and CI gates
**What.** A curated eval suite that runs automatically on every prompt, model, or tool change. CI gates block merges if key metrics regress beyond a threshold.
**Use when.** Any team shipping prompt or model changes more than once a month.
**Advantages.**
- Catches regressions before they reach production
- Forces discipline: every change must demonstrate non-regression
**Tradeoffs.**
- Flaky evals (due to non-determinism) cause false CI failures; requires thoughtful thresholds and retry logic
- Slow eval suites bottleneck development velocity
**Staff signal.** Set thresholds on the lower confidence bound, not the point estimate. This accounts for variance without being over-sensitive. A gate that says "95% CI lower bound must not drop below X" is more robust than "mean must not drop below X."

### Evaluating RAG components separately
**What.** Measure retrieval quality (recall@k, precision@k, MRR) independently from generation quality (faithfulness, relevance, completeness). This localizes failures: if retrieval recall is high but answers are wrong, the problem is generation; if recall is low, no amount of prompt engineering will help.
**Use when.** Debugging any RAG pipeline. Always evaluate components in isolation before evaluating end-to-end.
**Advantages.**
- Pinpoints whether to invest in better retrieval or better generation
- Prevents wasting effort optimizing the wrong component
**Tradeoffs.**
- Requires ground-truth relevance labels for retrieval eval, which are expensive to create
- Component-level metrics may not predict end-to-end quality if components interact non-linearly
**Staff signal.** If retrieval recall@10 is below 80%, fix retrieval first — generation cannot compensate for missing context. This single diagnostic saves weeks of misdirected prompt tuning.

### Failure taxonomy and error analysis
**What.** After running an eval, cluster failures into categories (wrong tool, hallucinated fact, context window exceeded, retrieval miss, format error, etc.), rank by frequency, and fix the largest bucket first. Repeat.
**Use when.** After every major eval run. This is the systematic quality improvement loop.
**Advantages.**
- Focuses engineering effort on highest-impact problems
- Builds institutional knowledge about failure modes
**Tradeoffs.**
- Manual clustering is time-consuming; semi-automated approaches (embedding + clustering) help but require validation
**Staff signal.** The second-largest failure bucket often has a simpler fix than the largest. Check the effort-to-impact ratio, not just frequency. A 15% bucket that can be fixed with a schema constraint is worth more than a 25% bucket requiring a model upgrade.

### Benchmarks vs your task
**What.** Public benchmarks (MMLU, HumanEval, GSM8K, etc.) measure general capabilities on specific distributions. They rarely predict performance on your specific task, domain vocabulary, or user population. Two models with similar benchmark scores can differ drastically on your workload.
**Use when.** Using benchmark scores for initial model shortlisting is fine; using them as the final selection criterion is not.
**Advantages.**
- Useful for rough model capability tiers and eliminating obviously unsuitable models
**Tradeoffs.**
- Benchmark contamination (training data overlap) inflates scores
- Your task's distribution, format, and difficulty likely differ from any benchmark
**Staff signal.** Always build a task-specific eval before choosing a model. A 5-point benchmark gap between two models tells you less than a 2-point gap on your own eval set. The cheapest model that meets your task-specific bar is the right model.

## Production evaluation

### Online metrics
**What.** Signals collected from real users: explicit feedback (thumbs up/down, ratings), implicit signals (task abandonment rate, escalation to human, retry rate, session length), and outcome signals (containment rate for support agents, task completion for workflow agents).
**Use when.** Measuring real-world quality after deployment. Offline evals are necessary but not sufficient.
**Advantages.**
- Captures user satisfaction on real distribution, including edge cases your eval set missed
- Implicit signals (abandonment, escalation) require no user effort and are high-volume
**Tradeoffs.**
- Noisy: users give thumbs-down for slow responses, not just wrong answers
- Selection bias: users who abandon do not leave feedback
**Staff signal.** Escalation rate and containment rate are the highest-signal online metrics for support agents. Track them as primary SLIs, and use thumbs-up/down as a secondary diagnostic.

### A/B testing agentic systems
**What.** Controlled experiments comparing agent variants on live traffic. Complicated by long feedback cycles (a multi-step agent task may take minutes to hours), high variance per session, and the need for guardrail metrics (safety, cost) alongside primary metrics.
**Use when.** Making model, prompt, or architecture changes that affect user-facing quality.
**Advantages.**
- Only way to measure causal impact on user behavior
**Tradeoffs.**
- Long sessions mean slow experiment convergence; you need more traffic or longer run time
- Guardrail metrics (cost, safety) must be monitored separately and can veto a winner on the primary metric
**Staff signal.** For agentic A/B tests, define a maximum cost-per-session guardrail upfront. A variant that improves quality by 5% but doubles cost is not a winner unless the business explicitly accepts the cost increase.

### Canary and staged rollout
**What.** Deploy model/prompt changes to a small fraction of traffic first (canary), monitor eval metrics, then gradually increase. Staged rollout enables fast rollback if quality degrades.
**Use when.** Any model, prompt, or tool change in production.
**Advantages.**
- Limits blast radius of regressions
- Gives time to detect slow-onset issues (e.g., increased loop rate visible only at scale)
**Tradeoffs.**
- Requires traffic-splitting infrastructure and per-variant metric tracking
- Small canary populations have high metric variance, making regression detection harder
**Staff signal.** Canary the model change and the eval pipeline simultaneously. If your eval metric itself has a bug, you want to catch it at low traffic, not after full rollout.

### Model upgrade regression ("silent regression")
**What.** When a model provider updates a model (new snapshot, quantization change, infrastructure migration), your system's behavior changes without any deployment on your side. These regressions are "silent" because your CI did not trigger and no code changed.
**Use when.** Any system that depends on a third-party model API without version pinning.
**Advantages.**
- Awareness motivates version pinning, continuous monitoring, and contractual SLAs
**Tradeoffs.**
- Version pinning delays access to improvements and may not be available from all providers
- Continuous monitoring against a golden set adds ongoing compute cost
**Staff signal.** Run your regression suite on a schedule (daily or weekly), not just on code changes. This is your early-warning system for provider-side changes. If a provider does not support version pinning, treat every day as a potential deployment day for that dependency.

### Cost and latency as eval dimensions
**What.** A correct but 30-second, $0.50-per-request response may be worse than a slightly less thorough 3-second, $0.02 response. Treat cost and latency as first-class metrics in your eval suite, with thresholds that gate deployment just like quality metrics.
**Use when.** Always. Cost and latency are quality dimensions, not afterthoughts.
**Advantages.**
- Prevents shipping technically correct but economically unviable agents
- Enables apples-to-apples comparison of different architectures (e.g., single large model vs orchestrated smaller models)
**Tradeoffs.**
- Optimizing for cost can degrade quality; these dimensions must be jointly evaluated, not separately
**Staff signal.** Report a Pareto frontier of quality vs cost for each architecture variant. If a variant achieves 95% of the quality at 30% of the cost, that is usually the production winner.

### Safety evals and red-teaming
**What.** A dedicated eval suite testing adversarial inputs, jailbreak attempts, harmful output generation, data leakage, and policy violations. Red-teaming is human adversarial testing conducted by specialists, not automated metrics alone.
**Use when.** Before launch, after major model changes, and on a recurring schedule.
**Advantages.**
- Catches risks that standard evals miss by design (they test for success, not for abuse)
**Tradeoffs.**
- Red-teaming is expensive and requires specialized skills; automated adversarial testing helps scale but misses creative attacks
**Staff signal.** Safety evals must run in a gated pipeline separate from quality evals. A model change that improves quality but regresses on safety must not ship. Make safety a hard gate, not a dashboard metric.

### Building an eval flywheel from production traces
**What.** Systematically mine production logs for failures (low-confidence outputs, user corrections, escalations, thumbs-down), cluster them, add the most informative cases to your golden dataset, and re-run evals. This creates a compounding loop: production failures make your eval set stronger, which makes your next release better, which generates fewer failures.
**Use when.** You have production traffic. This is how mature teams build eval sets that reflect real distribution rather than developer imagination.
**Advantages.**
- Eval set quality improves automatically over time
- Catches distribution drift: new user behaviors surface as new failure modes
**Tradeoffs.**
- Requires logging infrastructure, PII handling, and annotation effort
- Selection bias: you only see failures the system detects, not silent failures users accept
**Staff signal.** The flywheel only works if there is a low-friction path from "production failure identified" to "new eval case added." If adding a test case requires a multi-day process, the flywheel stalls. Invest in tooling that lets an engineer add a case in minutes.

## Common interview traps

- **Claiming "we test prompts manually and it works fine."** Manual testing does not scale, does not catch regressions, and gives no confidence intervals. Eval is infrastructure, not a one-time activity.
- **Reporting eval scores without confidence intervals or sample sizes.** A 2-point improvement on 50 examples with one run each is noise, not signal.
- **Using LLM-as-judge without calibrating against human labels.** The judge's biases become your quality bar.
- **Evaluating RAG end-to-end without separating retrieval from generation.** You cannot fix what you cannot diagnose.
- **Treating benchmark scores as predictive of production performance.** They measure different distributions.
- **Ignoring cost and latency in eval.** A correct but unaffordable system is a failed system.
- **Building a golden dataset once and never updating it.** Distribution drift makes static eval sets obsolete.
- **Running A/B tests on agents without guardrail metrics.** A quality win that triples cost is not a win.
- **Assuming temperature=0 means deterministic.** Quantization, batching, and provider-side changes introduce variance regardless.
- **Evaluating only final output, never trajectory, for agents with side effects.** A correct answer reached through an unsafe path is still a safety incident.

## Drill questions

1. You improved your agent's task completion rate by 4% on your eval set but cost per successful task went up 40%. How do you decide whether to ship this change?
2. Your LLM-as-judge agrees with human raters 75% of the time. What do you do before trusting it for CI gates?
3. Your RAG system's end-to-end accuracy dropped by 10%. Walk through the diagnostic process to determine whether retrieval or generation is at fault.
4. A model provider announces a new version of the model you depend on. What is your playbook for deciding when to migrate?
5. Your eval suite has 200 examples and runs 1× per example. An engineer claims a 2-point improvement on accuracy. Is this statistically meaningful? What would you change?
6. You discover that 5 of your golden test cases have leaked into your few-shot prompt. What is the impact and how do you remediate?
7. Your agent passes all eval tests but users report it "feels worse." What online metrics would you check and what might explain the discrepancy?
8. How would you design a trajectory eval for an agent that has three valid paths to the same correct answer?
9. Your safety eval suite has not been updated in 6 months. A new jailbreak technique is published. What process should exist to handle this?
10. You want to A/B test a new agent architecture, but each agent session takes 5–10 minutes. How do you design the experiment to converge in a reasonable time?
11. Describe how you would build the eval flywheel: from a production failure to a new test case to a shipped fix. What tooling is required?
12. When would you choose shadow evaluation over an A/B test, and what can shadow eval not tell you?
