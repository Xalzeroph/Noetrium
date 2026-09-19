# Noetrium Agent Method Coverage Audit

Date: 2026-09-03
Scope: current master after the Noetrium aggregation work, including research lifecycle, model/agent/environment contracts, evidence, experimentation, and the research workbench.

## Executive conclusion

Noetrium can host the core implementation of a broad class of Agent papers through injected Method, Model, Environment, Participant, Workload, and Study components. The platform does not need to contain every paper algorithm. The downstream method owns its algorithm; Noetrium owns lifecycle, capability binding, isolation, checkpoint identity, evidence, evaluation, and publication.

Before this audit, the platform was not sufficient for a complete paper workflow because numerical data preparation and publication were only contracts. The new research.workbench aggregate closes the common infrastructure gap with:

- immutable schema-bound DataTable values;
- source and transformation lineage digests;
- deterministic filtering, projection, derived columns, joins, aggregations, and train/test splits;
- random, stratified, group-preserving, and temporal split policies;
- shared numeric summaries, paired comparisons, Bootstrap intervals, and permutation comparisons;
- CSV and JSONL readers behind a reader port;
- CSV, Markdown, and LaTeX table output behind a renderer port;
- deterministic SVG line, bar, scatter, histogram, boxplot, heatmap, and uncertainty/error-bar output;

The workbench is standard-library-first. Pandas, NumPy, SciPy, Matplotlib, PyTorch, vector databases, and simulator SDKs remain downstream or provider adapters. This keeps the public method surface decoupled from vendor details.

## Coverage matrix

| Method family | Platform seam | Verdict | Boundary |
|---|---|---|---|
| ReAct, tool-use, function calling | Agent loop, capability operation, effect journal, recovery | Strong | Downstream supplies tool policy and tool provider |
| RAG and evidence-grounded agents | Evidence query, source snapshots, artifact references, model capability | Strong with adapter | Vector/full-text index and embedding model are provider concerns |
| Memory, skill learning, reflection | Memory/skill ports, checkpoint envelope, participant runtime identity | Strong | Downstream defines memory semantics and storage adapter |
| Planning, ToT, GoT, MCTS, search | Whole-method host and stateful method program | Strong | Search algorithm is downstream code; checkpoint state is injected |
| Single-agent RL and PPO | Environment, MethodProgram, Study matrix, checkpoints, measurements | Method-host ready | Tensor trainer, replay buffer, GPU loop, and RL library are not platform core |
| MARL and multi-agent coordination | Participant topology, orchestration transport, shared study/workload seams | Method-host ready | Domain simulator and communication/game algorithm are downstream |
| Embodied, web, GUI, browser agents | Environment action/observation contracts and capability effects | Provider-ready | Browser/game/robot backend must be supplied |
| World models and model-based planning | Model capability, stateful method, artifact/checkpoint identity | Method-host ready | Tensor storage/training backend is downstream |
| Multi-modal/VLM agents | Typed model capability families and environment artifacts | Provider-ready | Image/video/audio preprocessing backend is downstream |
| Long-horizon autonomous agents | Run control, evidence validity, recovery and durable artifacts | Strong | Domain task decomposition remains downstream |
| Benchmarking and ablations | Variant bindings, deterministic assignments, study matrix, workload graph | Strong | Paper-specific factor definitions are downstream |
| Data processing and feature preparation | DataTable, TablePipeline, joins, aggregations, split policies | Strong common core | Parquet/Arrow/database/cloud readers and domain transforms need adapters |
| Statistical evaluation | ScientificStatistics, summaries, paired/effect/resampling tests, missing policy | Strong common baseline | Mixed-effects, exact domain tests, power analysis and multiple-comparison families need an adapter |
| Paper tables and plots | StandardTableRenderer, SvgFigureRenderer, error bars, boxplots, heatmaps, report digest | Strong common core | Matplotlib/Plotly/seaborn styling and journal templates are output adapters |
| Reproducibility and provenance | Dataset versions, measurement cuts, analysis identity, artifacts | Strong | Physical storage and external dependency lockfiles stay outside core |

## What implementable downstream means

A paper is implementable downstream when its novel method can be written as a typed MethodProgram or a composed Agent/Model/Environment component, while the platform supplies:

1. a frozen project and method binding;
2. a deterministic workload/study matrix;
3. an environment and model capability adapter;
4. run-local checkpoints and evidence artifacts;
5. structured measurements;
6. a single analysis and publication path.

This is deliberately different from putting a generic run() function into every paper project. The method may remain completely paper-specific, but the experiment mechanics are shared.

## Remaining platform-level limits

The audit does not claim that the core package itself is a full ML framework. The following are intentionally provider or downstream responsibilities:

- GPU/distributed execution and accelerator-specific tensor storage;
- Transformer, diffusion, VLM, simulator, browser, robotics, and vector-index implementations;
- domain-specific replay buffers, neural optimizers, schedulers, and loss functions;
- advanced inference such as mixed-effects models, permutation/bootstrap families, multiple-comparison correction, power analysis, and inter-rater reliability;
- high-volume Parquet/Arrow/database ingestion;
- publication-specific journal templates and typography.

These are extension points, not reasons to duplicate lifecycle, lineage, metrics, or plotting code in each paper.

## Architectural decisions retained

- Existing Dataset, Measurement, Study, Analysis identity, and Artifact authorities remain authoritative.
- research.workbench is an aggregation layer over those authorities, not a replacement experiment system.
- Physical file locations are never part of table, analysis, or figure identity.
- Every transformation that changes research data requires an explicit operation and configuration digest.
- Numeric output uses finite-value validation and explicit missing-value policy.
- Figure and table formats are output concerns; downstream methods do not import plotting libraries.
- Public downstream authors may import the stable noetrium.contracts.research surface without learning internal package paths.

## Audit conclusion

The architecture is sufficient for the core method of most Agent-paper families, provided the method-specific backend is injected. It was not sufficient for the surrounding scientific workflow until the research workbench was added. The main follow-up is to add optional scientific backend adapters and richer statistical procedures without moving those vendor-specific details into the public contracts.

## Deep downstream method reasoning

The matrix is a capability-family judgment, not a claim that the platform contains every algorithm from every paper. The correct downstream implementation pattern is:

| Paper contribution changes | Downstream owns | Noetrium reuses |
|---|---|---|
| Prompt/tool policy or ReAct loop | policy, tool schema, provider calls | turn lifecycle, effects, evidence, recovery, measurements |
| Retrieval, reranking, citation grounding | index/embedding/reranker adapter and grounding policy | content identity, evidence cuts, result provenance, evaluation |
| Memory, reflection, skill acquisition | memory semantics and storage implementation | participant identity, checkpoint envelope, task completion |
| Planner/search/world model | search/state transition/model implementation | stateful method host, run isolation, checkpoints, study matrix |
| PPO, offline RL, MARL | simulator, tensor backend, replay/loss/optimizer | trial/run boundary, seed/repetition design, metric/evidence path |
| Vision/audio/video/GUI/robotics | media preprocessing and environment provider | content refs, action/effect boundary, failure/recovery |
| Benchmark/ablation/generalization | factor definitions and task cut | compiled variants, assignments, paired comparability |
| Publication analysis | domain-specific estimator or styling adapter | immutable tables, statistics, figure identity, report digest |

A method is “downstream implementable” only if its novel control graph can be expressed through the typed whole-method program or composed public Agent/Model/Environment capabilities, and all observations/results can enter the shared Measurement/Artifact/Evidence path. A method is not considered fully supported merely because a generic run() function can execute it.

### Paper infrastructure closure

The common paper path is now:

1. Reader adapter produces a schema-bound DataTable with source digest.
2. TablePipeline performs explicit transforms, joins, aggregation, and split policy; each output carries parent and configuration lineage.
3. Trial/run emits typed measurements and durable evidence/artifacts.
4. The study matrix repeats variants, seeds, repetitions, and workload cuts under one plan; `StudyConcurrencyPolicy` freezes both repetition-level and variant-level fanout.
5. Independent variant fanout uses `StudyVariantExecutionPort` (or its compiled-plan counterpart) and the injected structured task group; a missing capability fails closed instead of silently serializing or bypassing the plan.
6. ScientificStatistics creates summaries, paired effects, and reproducible resampling results.
7. FigureSpec consumes semantic series/cells, including uncertainty, and a renderer emits SVG or a downstream backend emits publication styling.
8. ResearchReport binds the tables/figures and exposes one report digest.

This is the aggregation boundary: paper projects should not create a second data frame authority, metric aggregation authority, plotting authority, or provenance scheme.

### Plotting decision

The standard-library SVG renderer is intentionally suitable for deterministic smoke tests, dashboards, lightweight reports, and environments where scientific plotting packages are unavailable. It covers the common figure semantics needed by Agent papers: learning curves, method comparison bars, scatter/error plots, distributions, boxplots, and matrix heatmaps.

For publication-quality work, the downstream project should implement one FigureRendererPort adapter around Matplotlib, Seaborn, Plotly, Vega, or a journal-specific renderer. That adapter receives the same FigureSpec; it must not redefine experiment data, metric names, uncertainty semantics, or provenance. This gives the project high-quality typography without exposing plotting-library types to the method or changing figure identity.

### What “strong enough” means by method family

- ReAct/tool/RAG/memory/planning/long-horizon methods: platform-level path is strong; only method/provider semantics remain downstream.
- Benchmark, ablation, seed/repetition, paired evaluation, generalization, and common metric/report workflows: platform-level path is strong after the workbench additions.
- PPO, offline RL, MARL, world models, diffusion/VLM, browser/GUI, robotics, and distributed training: the experiment architecture is ready, but the scientific backend is necessarily injected. The platform must not pretend to provide GPU kernels, simulators, browser automation, model weights, or tensor optimizers.
- Advanced statistical claims: the shared result types are available, but a paper requiring mixed-effects, non-parametric exact tests, bootstrap variants, multiple-comparison correction, calibration, survival analysis, causal estimands, or inter-rater reliability must bind a specialized TableAnalysisPort/statistics adapter. It must return immutable results with the same source and configuration identities.
- High-volume datasets: the in-memory DataTable is the portable value boundary, not a claim that all data must be materialized in memory. A streaming/Arrow/database adapter should implement the reader/transform/analysis ports and emit the same semantic cut and digest contracts.

### Audit rule

When a future paper is evaluated, check the full chain rather than the algorithm label:

method input -> model/environment seam -> trial/run -> measurement/evidence -> analysis -> table/figure -> report

A green method seam with a red analysis or publication seam is not a complete paper implementation. Conversely, a backend-specific implementation is acceptable when it is isolated behind the shared ports and does not duplicate lifecycle, lineage, comparison, or plotting semantics.

## Lifecycle convergence update

The public research seam now adds the missing identity and orchestration layer:

- EvaluationContext binds project, experiment, study, candidate, stage, dataset cut, split, protocol, code revision, configuration, seed, and optional run identity into one digest. Test, shadow, and live stages are explicitly marked locked.
- BaselineSpec and BaselineRegistryPort define one reusable reference-method authority. InMemoryBaselineRegistry is the portable default; durable catalogs can implement the same port. Dataset and protocol drift is rejected before comparison.
- ResearchLifecycle is the downstream-facing aggregate. It validates identity, adapts study observations into the shared table, computes summaries and baseline/candidate effects, and returns one ResearchEvaluation containing the immutable table, statistics, figures, and ResearchReport.
- The study public __all__ surface was corrected so wildcard imports do not advertise symbols that are not defined by that package. Compiler contracts remain owned by the experimentation API.
- Temporal splits now sort typed numeric, boolean, and text keys by value rather than by repr, preventing chronological leakage caused by lexicographic ordering such as 10 before 2.

This preserves the existing aggregation: ExperimentRunApplication remains the run/study execution owner, ExperimentProgramBinding remains the matrix/concurrency owner, Measurement and Evidence remain result/provenance owners, and the workbench remains the analysis/publication owner. The new lifecycle is a facade over those authorities, not a second implementation of them.

## Cross-system convergence findings

The large directory counts are not, by themselves, duplicate execution systems. The audited boundaries are:

| Concern | One execution/semantic authority | Other layers |
|---|---|---|
| Structured concurrency | foundation.kernel.concurrency runtime and task-group ports | governance scans, admission/scheduling composition, and provider executors |
| Study parallelism | ExperimentProgramBinding plus StudyConcurrencyPolicy | kernel task group supplies execution capacity |
| Logging | StructuredLoggingSystem / LoggingSystemPort | record, sink, query, retention and diagnostic projections |
| Runtime metrics | telemetry metric contracts and ContextMetricSink | composition observers emit domain facts |
| Raw method observations | RawObservationLake and capture receipts | method sink is only an adapter |
| Scientific measurements | MeasurementProtocol / MeasurementRecord | workbench adapters project them once into DataTable |
| Artifacts and evidence | artifact/reference and evidence-bundle authorities | run publication composes immutable receipts |
| Experiment lifecycle | run → study → trial hierarchy | environment/model/method providers realize injected capabilities |

The rule for future additions is strict: a new subsystem may add a provider, projection, or adapter, but it may not introduce a second scheduler, logger, metric ledger, measurement aggregator, baseline catalog, table authority, figure semantic model, or provenance digest. If a new paper needs a richer backend, it must implement the existing port and return the existing identity-bearing result types.

## Current strength boundary

The platform is strong enough for downstream implementation of the control graph and complete common paper workflow across ReAct/tool use, RAG, memory/skills/reflection, planning/search, long-horizon agents, benchmark matrices, ablations, seed/repetition studies, and environment/model-provider variants. It is intentionally not a replacement for the provider's tensor kernels, simulator, browser/robotics SDK, embedding/vector index, or journal-specific statistics/renderer.

Supported therefore means: the paper's novel method can be injected through the typed method/model/environment/participant seams; every run enters the shared assignment, checkpoint, measurement/evidence and artifact paths; and every claim can be reproduced through the shared evaluation context, data table, analysis, figure and report identities. A provider-specific algorithm is acceptable only behind these ports.

## Second-round closure

The follow-up audit found two practical weaknesses in the first public seam and closed them without adding a second authority:

- ScientificStatistics.compare_many and the optional candidate_values argument now compare every declared method against one baseline in one deterministic operation. The result preserves the legacy primary comparison while exposing the complete comparison tuple, so downstream papers do not silently report only the first candidate.
- ResearchLifecycle.evaluate_measurement_records and evaluate_trial_report now bridge authoritative scalar MeasurementRecord and TrialMatrixExecutionReport values into the same DataTable/statistics/figure/report path. Project, study, and optional run identity are checked before projection; the lower-level measurement system remains the sole owner of measurement semantics.
- RenderedResearchPackage is now reachable from the stable top-level contracts, and the lifecycle render facade binds table and figure output to the evaluation digest.
- Public trial/measurement contracts are exported through the stable research contract surface, so downstream authors do not need to import internal package paths.

The resulting downstream lifecycle is:

compiled research plan -> ExperimentProgramBinding or TrialProvider -> Measurement/Study report -> ResearchLifecycle -> one or many baseline comparisons -> immutable report -> renderer package

This is the intended level of decoupling. Method authors can replace the model, simulator, retrieval index, tensor trainer, browser, robotics environment, advanced statistics backend, or publication renderer through ports. They cannot accidentally create a second measurement ledger, comparison authority, table schema, plot semantic model, or provenance digest.

The remaining boundary is deliberate: a paper requiring mixed-effects models, multiple-comparison correction, power analysis, causal estimands, or a domain-specific media/database backend should implement the existing analysis/reader/renderer port and return identity-bound results. It should not copy the lifecycle or add a parallel scheduler/logger/metric registry.

## Third-round closure: publication and baseline strength

The publication seam now exposes two stronger high-level authorities:

- ResearchFigureFactory converts an immutable DataTable into semantic learning curves, repetition-aware benchmark bars, distributions, matrices/confusion matrices, Pareto plots and baseline effect/forest plots. It computes mean and 95% intervals through one shared path, pins source table digests, and leaves renderer-specific types behind FigureRendererPort.
- FigureStyle provides deterministic Nature and Science-oriented palettes, typography, spacing tokens, grid/background controls, uncertainty styling and transparent-output policy. SvgFigureRenderer consumes these tokens and adds violin and ECDF rendering while retaining the same FigureSpec identity. Matplotlib/Seaborn/Plotly/journal backends can implement the same port without redefining semantics.

Baseline management is also strengthened without introducing a second catalog authority:

- BaselineSpec now records reference, source URI, license and tags in its digest, so a baseline comparison is traceable as a scientific object rather than only an implementation name.
- BaselineRegistryPort.catalog() and the deterministic in-memory implementation expose the complete registered baseline catalog for audit, selection and report generation.
- Dataset/protocol compatibility remains validated before evaluation; baseline metadata cannot silently change an existing baseline identity.

The intended downstream path is now:

method/provider -> frozen run/study matrix -> authoritative measurements -> DataTable projection -> shared statistics -> ResearchFigureFactory -> FigureSpec + FigureStyle -> renderer adapter -> ResearchReport/RenderedResearchPackage.

This adds public strength at the semantic layer while preserving the convergence rule: no downstream paper creates its own figure model, confidence-interval implementation, baseline registry, measurement ledger, scheduler, logger, or provenance digest.

## Fourth-round closure: inferential evidence and diagnostic plots

The shared workbench now closes two publication-critical gaps:

- `ScientificStatistics.adjust_p_values` is the single multiplicity authority for Bonferroni, Holm, Benjamini-Hochberg and Benjamini-Yekutieli correction. `MultipleComparisonResult` preserves raw p-values, adjusted p-values, decisions, alpha and a result digest; `compare_many` attaches raw and Holm-adjusted values to every baseline comparison.
- `ResearchFigureFactory.classification_curve` provides stable ROC, precision-recall and calibration semantics. The renderer uses numeric x coordinates, adds a reference diagonal for ROC/calibration, and applies one style-controlled grid policy across line, distribution, ECDF and classification figures.

These are intentionally backend-neutral. The built-in implementation covers deterministic/common cases; specialized tests, mixed-effects models, survival/causal estimands, power analysis, or journal-specific annotation layout still bind through `TableAnalysisPort`/`FigureRendererPort`. The downstream contract remains one table, one statistics authority, one figure specification, and one provenance path.

## Fifth-round closure: categorized publication artifacts and PDF-first output

The figure system now has an explicit semantic category derived from FigureKind, so downstream code can group figures without recreating classification logic:

| Category | Figure kinds |
|---|---|
| trend | line |
| comparison | bar, scatter |
| distribution | histogram, boxplot, violin, ECDF |
| matrix | heatmap, confusion matrix |
| classification | ROC, precision-recall, calibration |
| tradeoff | Pareto |
| effect | forest |

PublicationFigureRenderer is the stable downstream facade. It defaults to deterministic vector PDF and accepts explicit SVG output. PdfFigureRenderer is standard-library-only, returns a portable base64 data URI, and preserves the same FigureSpec semantics, source digests and style tokens. SVG remains available for web/authoring workflows. A journal-specific backend can implement FigureRendererPort when it needs native font embedding, LaTeX text, panel composition or journal templates.

This closes the output contract without moving rendering details into the lifecycle: ResearchLifecycle.render selects the output format, RenderedResearchPackage records it, and the provider owns serialization. The same immutable figure specification can therefore be rendered to PDF, SVG, or an external backend without recomputing statistics or creating a second provenance path.

Design inspiration was reviewed from [SciencePlots](https://github.com/garrettj403/SciencePlots), [mplscience](https://github.com/adamgayoso/mplscience), [statannotations](https://github.com/trevismd/statannotations), and [Seaborn](https://github.com/mwaskom/seaborn). Their composable publication styling, vector-output concerns, statistical annotation model and high-level plot semantics informed the contracts; no external source code was copied. The built-in backend remains intentionally lightweight so core installation does not force heavyweight numerical/plotting dependencies.
