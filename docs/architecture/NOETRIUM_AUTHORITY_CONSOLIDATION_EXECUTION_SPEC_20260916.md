# Noetrium Authority Consolidation & Research OS Execution Spec

> Status: **Normative vNext execution specification**
> Date: 2026-09-16
> Scope: Noetrium Research Agent OS architecture, authority topology, execution kernel, persistence, providers, governance and migration
> Supersedes for authority classification: `VNEXT_DETAILED_SYSTEM_MAP.md`, `VNEXT_SYSTEM_CATALOG.json`, and the fine-grained system decomposition portions of `REFACTORING_VNEXT_DESIGN.md`
> Preserves and sharpens: `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md`

## 1. Executive decision

Noetrium will be refactored from a directory-shaped collection of nominal systems into an **authority-shaped Research Agent OS**.

The central rule is:

> **A subsystem is an authority only when it owns acceptance of truth, irreducible mutable state, a fenced/CAS state transition, scientific identity/equivalence, external-effect certainty, or an immutable binding/source cut.**

Everything else is a contract facet, projection, provider, adapter, codec, policy, tool, query surface, or product surface.

The current catalog must therefore stop treating every replaceable package or recursive leaf as an independent authority.
## 2. Why this refactor is necessary

Repository audit found two simultaneous topology errors.

First, the system registry contains many nominal systems that are only thin wrappers, re-exports, schemas, views, validators, query surfaces or provider-specific packages. Examples include `portfolio/project`, most `scope/*` leaves, `operator/*` leaves, several model/environment leaves, and governance AST-analysis packages.

Second, the actual codebase contains many state-owning classes that are not represented by the nominal topology at all. A repository-wide scan found 275 classes whose names carry authority-like semantics: 108 `Store`, 49 `Registry`, 25 `Journal`, 24 `Authority`, 23 `Coordinator`, 19 `Runner`, 11 `Supervisor`, 10 `Scheduler`, and 6 `Loop` classes.

The number itself is not the defect. The defect is that the current topology cannot distinguish:

- authoritative state from projection/cache/storage implementation;
- durable truth from convenience indexing;
- research semantics from infrastructure mechanics;
- provider runtime from platform authority;
- build-time governance from runtime governance;
- product/UI surfaces from domain state ownership.

A catalog that over-registers facades while under-registering real mutation owners is not a trustworthy architecture description.
## 3. Authority qualification test

A node may be registered as an authority only when at least one of the following is true:

1. **Truth acceptance** — it decides whether a fact or transition becomes authoritative.
2. **Irreducible mutable state** — it owns state that cannot be deterministically rebuilt from another authority.
3. **Concurrency ownership** — it performs CAS, fencing, generation, lease or equivalent serialization over that state.
4. **Scientific identity** — it determines frozen identity, equivalence, admissibility, comparability or source-cut semantics used by research claims.
5. **Effect certainty** — it decides whether an external effect is prepared, executed, rejected, unknown, reconciled or consumed.
6. **Immutable binding** — it owns a frozen manifest, binding, content identity or source cut whose change has semantic consequences.

The following are **not authorities by themselves**:

- codecs and serializers;
- schema declarations;
- validation helpers;
- projections and indexes;
- caches;
- CLI and UI layers;
- read/query services;
- repository AST/import analyzers;
- filesystem/SQLite implementations of an already-declared port;
- vendor/provider adapters;
- convenience wrappers and re-export packages;
- policy objects with no authoritative mutation.
## 4. Required node kinds

Every catalog node must declare one explicit kind. The target vocabulary is intentionally small:

- `authority` — accepts or mutates authoritative truth.
- `facet` — semantic subdivision of a parent authority; no independent truth store.
- `projection` — rebuildable/materialized read model derived from authority facts.
- `provider` — concrete implementation of a stable port or external integration.
- `adapter` — translates one contract into another without owning truth.
- `policy` — pure or declarative decision logic evaluated by an authority.
- `tool` — build-time/development/operator utility; not part of runtime truth topology.
- `product_surface` — CLI/UI/application/query surface over authorities.

A node marked `facet`, `projection`, `provider`, `adapter`, `policy`, `tool`, or `product_surface` may remain in source layout and documentation, but it must not be represented as an independent state authority.

The registry must reject ambiguous nodes with no kind, and must reject `authority` nodes with no explicit `owns`, `must_not_own`, identity boundary, and durability/effect classification.

## 5. One authority, one implementation owner

No logical state authority may be split across Python, Rust, Go, TypeScript, Java or any other language merely for implementation convenience.

Cross-language boundaries must coincide with provider/adapter/runtime boundaries. Language is an implementation property, never a scientific identity dimension unless the language/runtime artifact materially changes execution semantics and is therefore frozen as provenance.
## 6. Single execution truth: Machine Journal

The most important convergence is between the generic Machine kernel and the Universal Method Machine.

Today `MachineExecutor` already owns durable command acceptance, journal transitions, replay, snapshots, authority leases, outbox delivery and child-machine relationships. UMM separately owns node execution, method state, progress, checkpointing and resumable control. The former coarse `MethodMachineInterpreter` wrapped an entire UMM run inside one Machine transition and has now been removed. Node-level method truth is committed through `MachineMethodTransitionAuthority`, while UMM remains the method interpreter.

The target invariant is:

> **Any change to scientific execution truth must be committed as a Machine transition.**

UMM remains the universal research-method interpreter, but ceases to be a second durability authority.

Target flow:

```text
MethodProgram / ExperimentPlan / AgentMethod
                ↓
      Method interpreter / compiler
                ↓
      node or control decision
                ↓
          MachineCommand
                ↓
          MachineExecutor
                ↓
       TransitionProposal
                ↓
        Machine Journal commit
```

A method node may compute a proposal, call a pure capability, prepare an effect intent, interrupt or checkpoint; the accepted transition is authoritative only after the Machine kernel commits it.
### 6.1 Consequences

- `AgentCognitionLoop` becomes a reference method/program composition, not a second platform loop authority.
- `experimentation/workload` cannot hard-code `observe → recall → plan → act → completion`; workloads provide task/environment/completion adapters and are invoked by Method/Machine execution.
- `UniversalExperimentRunner` expands study/experiment plans into run/machine invocations; it does not own another scientific execution loop.
- UMM checkpoint/progress storage becomes Machine-backed state/projection rather than a competing truth source.
- Agent Turn facts are Machine events/projections over the same committed transition history.
- Method interrupts become committed wait states, not opaque Python control flow.
- Resume begins from an accepted journal cut plus optional verified snapshot acceleration.
- Node-level effect references must bind to the same committed transition that advances method state.

### 6.2 Checkpoint rule

A checkpoint is **not a second authoritative state history**. It is a verified acceleration artifact containing enough state to resume from a specific committed transition/journal cut.

A valid checkpoint therefore binds:

- machine identity and family;
- program digest;
- committed transition/journal position;
- state digest;
- relevant operation/effect cut;
- immutable artifact/content identities;
- runtime identity only where recovery semantics require it.

If journal and checkpoint disagree, journal authority wins and the checkpoint is rejected.
## 7. Experimentation convergence

Experimentation owns scientific planning semantics, not a second runtime kernel.

Retain as scientific authorities/frozen identities where irreducible:

- Study definition/hypothesis/protocol identity.
- Experiment definition and treatment/variant assignment semantics.
- Run frozen manifest/identity and high-level lifecycle intent.
- Branch lineage where it changes scientific execution ancestry.
- Evaluation definitions and claim-relevant result identity.

Demote to facets/projections/adapters:

- workload phase loops;
- generic runner loops;
- checkpoint stores as independent truth;
- workbench-local statistics/plot execution mechanics;
- catalog/query views;
- repeated run identity/lifecycle/manifest leaf systems when the parent Run authority already owns them.

The experiment compiler produces a deterministic set of Machine invocations. Resource allocation, runtime launch and model/environment binding are external authorities referenced by receipts; they are not embedded mutable experiment state.

## 8. Participant and Agent convergence

`participant` remains the platform abstraction for a research actor identity/binding/session contract. `agent` is one participant kind and must not own a platform-global cognition loop.

Paper-specific planning, reflection, search, memory scoring, tool policy and multi-agent coordination remain MethodProgram/downstream semantics unless a mechanism is demonstrated to be method-independent across reproductions.
## 9. Environment boundary

The generic Environment authority owns only provider-independent environment semantics:

- environment/spec identity;
- session identity and lifecycle contract;
- observation/action request/response ABI;
- capability declaration;
- checkpoint/fork/reconcile contract;
- effect reconciliation boundary;
- provider readiness/binding facts required for reproducibility.

Environment-specific packages such as Minecraft, GUI, Web, Software and TextWorld are providers/adapters unless they own a distinct irreducible environment state authority.

The Minecraft audit found platform leakage of recipe graphs, resource planning, blueprint logic, task success, combat policy, reactive self-defense, skill catalogs and a cognition runner. These are not generic environment authority.

Migration target:

```text
Minecraft Provider
├── world/session I/O
├── action/observation translation
├── checkpoint/fork/reconcile implementation
└── readiness/runtime binding

Benchmark Adapter
└── task success / benchmark-specific reset and scoring

Method / Reference Agent
└── planning / skills / combat / cognition / policy
```

No provider package may silently become a method implementation simply because the benchmark originally shipped the two together.
## 10. Model boundary

Noetrium must retain the scientific model semantics needed for exact reproducibility:

- requested model capability and role;
- exact asset/revision identity;
- frozen serving/deployment binding identity;
- prompt/request/response provenance;
- qualification claim/evidence identity;
- model-service admission policy where it protects shared research capacity and isolation.

Noetrium should not become a package manager, CUDA dependency solver or inference engine.

The qualification audit shows current logic understands PyPI wheels, CUDA package names and backend-specific dependency closure. Those mechanics must migrate behind toolchain/model-serving providers. Platform contracts should express requirements and verified evidence, not vendor package graphs.

`model/catalog/revision` is a separate mutable revision/promotion state machine. It must be retained only when model evolution is an enabled research capability; it must not be mandatory infrastructure for an ordinary fixed-model Agent experiment.

Shared serving is the default reuse path when identity, health, isolation and capacity are compatible. Scientific identity records the exact qualified binding; it does not require one process per experiment.

## 11. Unified Artifact/Content authority

The repository currently contains multiple content-addressed stores, including the formal Artifact content subsystem, model-request content storage, and kernel-level CAS utilities.

The target is one immutable content authority and one reference model. Model multimodal blobs, datasets, checkpoints, evidence payloads and ordinary artifacts reference the same content-addressed substrate instead of inventing domain-local blob stores.
Artifact subdomains become facets unless they independently satisfy the authority test:

- catalog metadata and immutable content identity remain authoritative semantics;
- lineage is an immutable relationship facet over artifact identities;
- aliases/references are a reference facet unless mutable alias resolution is enabled;
- retention is policy plus retention-state mutation, not a new scientific truth source;
- acquisition/download/materialization are providers;
- filesystem/SQLite stores are implementations.

Cross-boundary data transport follows payload type rather than forcing JSON everywhere:

- semantic/control ABI: canonical JSON/schema and typed envelopes;
- tabular/columnar data: Arrow-compatible representation;
- tensors: DLPack/framework-native buffers where safe;
- large immutable bytes: content-addressed references;
- native in-process boundary: stable native/C ABI when justified;
- untrusted portable plugin boundary: WASM/WIT where appropriate.

## 12. Data authority vs query execution

Noetrium retains research data semantics that affect reproducibility: durable facts, source cuts, research dimensions/result references, projection watermarks and immutable dataset identities.

It does not need to own a general-purpose analytics engine or vector-search implementation.

Operational authority may remain SQLite-backed for small, strongly consistent state. Analytic execution should be delegated through providers such as Arrow/Parquet plus DuckDB/DataFusion/Polars. Semantic indexes may use FAISS/Qdrant/pgvector or equivalent providers.

External query engines return derived results bound to a Noetrium source cut. They never become the authoritative source of scientific facts merely because they execute the query.
## 13. Resource authority convergence

Resource lifecycle currently duplicates lease semantics across generic resource leases, endpoint allocation and compute allocation. The target is one lease/fencing authority reused by all resource kinds.

```text
ResourceLeaseAuthority
├── holder / owner identity
├── TTL / renewal / expiry
├── fencing generation
└── release / reconciliation
        │
        ├── ComputePlacement facet/provider
        ├── EndpointBinding facet/provider
        ├── Directory/Workspace facet/provider
        └── future external scheduler bindings
```

Compute owns requirement/capacity/placement semantics, not a second lease lifecycle. Endpoint allocation owns address selection and OS binding proof, not a second lease lifecycle.

External schedulers such as Ray, Slurm, Kubernetes/Kueue or equivalent may own physical placement mechanics. Noetrium retains logical demand, scientific resource policy, binding receipt, isolation requirements and reproducibility-relevant provenance.

Resource reuse is allowed only under:

> Exact identity + health/readiness + isolation compatibility + capacity compatibility.

Idle-first placement is preferred. Safe residual sharing is allowed. Pressure blocks new admission rather than killing already admitted Noetrium work by default.
## 14. Reliability and forensic truth

Reliability is retained, but truth ownership must be reduced rather than multiplied.

Primary execution authorities are expected to include Machine transitions, Operation state, Effect state, immutable Artifact/content identities, selected durable scientific facts, and explicit failure facts.

Forensics should primarily materialize tamper-evident evidence and rebuildable diagnostic indexes from those facts:

```text
Machine / Operation / Effect / Artifact / DurableFact
                      ↓
              evidence materialization
                      ↓
        hash ledger / forensic index / crash bundle
```

A forensic index is always disposable. A hash-chained forensic materialization may be durable evidence, but it must not invent a second mutable business state.

Failure taxonomy is a schema/policy facet; an actual `FailureEnvelope` is a durable fact. Diagnostics is read-only correlation over authorities and projections.

Recovery plans are policy/coordination. Recovery ownership must use the unified lease/fencing authority instead of maintaining a parallel ad-hoc recovery lease implementation.

## 15. Governance contraction

Repository architecture, complexity, concurrency and performance analyzers are build-time tools/gates. They are not runtime business authorities.

`governance/architecture`, `governance/algorithm`, `governance/concurrency`, repository-boundary analysis and similar AST/import/source profiling move conceptually to `tools/gates` or equivalent build-time surfaces.

Runtime governance retains only policy whose decision materially constrains executable contracts: schema compatibility, security/redaction policy, release identity/promotion, system/authority topology and explicit runtime gates.
## 16. Operator is a product surface

`operator` is not an independent durable domain authority.

The audit shows its responsibilities are project scaffolding, project doctor checks, run-control translation, management commands, search/query, diagnostics and reference/conformance applications.

Target classification:

- project scaffold/doctor/test → product tooling;
- run-control research application → adapter/facade over Run authority;
- maintenance commands → product surface over domain authorities;
- query/search/incident views → read-side product surfaces;
- reference application → conformance/reference test implementation.

Operator code may remain substantial and important while staying outside the authority topology.

## 17. Scope contraction

There is one Scope authority for hierarchy truth. `ScopeIdentity`, hierarchy, ancestry and parent links are facets of that authority.

`scope/identity`, `scope/hierarchy`, `scope/membership`, `scope/ownership`, `scope/resolution` and `scope/path` must not be separate mutable authorities unless a future requirement introduces genuinely independent truth.

Path flavor/normalization is a utility/provider concern, not a system authority.

## 18. Portfolio contraction

There is one Portfolio authority for workspace/program/project metadata and canonical ProjectManifest state. Scope remains the hierarchy authority.

`portfolio/workspace`, `portfolio/program`, `portfolio/project` and `portfolio/membership` are facets/views over Portfolio. The existing project leaf already re-exports the root canonical contracts, which confirms that it is not a separate authority.
## 19. Runtime and lifecycle boundary

Runtime owns process/service/session/host lifecycle facts needed to materialize execution. It must not duplicate research Run state.

A service/process supervisor may own the lifecycle of an operating-system resource; the Research Run owns only its frozen binding and scientific execution status. The two are connected by immutable identities and receipts.

Process command execution is a provider mechanism. Service supervision is infrastructure authority only where it owns real process/service lifecycle state. Server/health/identity leaf packages become facets unless they carry independent state transitions.

Python environment management is one runtime/toolchain provider family, not the definition of the Runtime system. Future Node/JVM/native/WASM providers must bind through the same provider-runtime descriptor and resource/materialization contracts.

## 20. Polyglot implementation model

Noetrium is **Python-first, language-neutral and polyglot-capable**.

- Python remains the main research/control/evidence language.
- TypeScript/Node is first-class for browser, Mineflayer and Node-native providers.
- Rust is the preferred future systems substrate when profiling proves a hot path or a low-level runtime capability requires it.
- Go is a possible node-agent/cloud-control implementation when cloud-native operational integration dominates; it must not duplicate a Rust/Python scheduler authority.
- C++/CUDA/HIP/Triton are reused through ML/HPC providers and kernels rather than becoming the control plane.
- JVM/C#/Julia/R are provider ecosystems, not core rewrites.
- WASM/WASI/WIT is the preferred long-term portable sandbox boundary for suitable untrusted plugins.
- Shell remains deployment/bootstrap glue only.

A new language requires an explicit RFC showing ecosystem or performance gain greater than build, deployment, debugging, ABI, security and maintenance costs.
## 21. Target top-level architecture

The target is not one authority per source directory. The stable top-level responsibility map is:

```text
Scientific semantics
├── Portfolio / ProjectManifest
├── Study / Experiment / Run scientific contracts
├── MethodProgram / Participant / Evaluation
└── Evidence identity / source cuts

Research execution
├── Method compiler/interpreter
├── Machine families
├── Operation / Effect coordination
└── Admission / scheduling policy

Durable kernel
├── Machine authority + Journal
├── Operation authority
├── Effect authority
├── Scope authority
├── Resource lease authority
└── immutable Artifact/Content authority

Infrastructure/provider plane
├── Model serving
├── Environment providers
├── process/service/session runtime
├── compute/storage/network providers
└── external engines/toolchains

Read/product plane
├── projections/query/analytics
├── observability/diagnostics/forensics
└── operator/CLI/UI
```

Top-level domains may expose many contracts without multiplying durable authorities.
## 22. Domain disposition summary

| Domain | vNext disposition | Core action |
|---|---|---|
| platform/kernel | KEEP + CONSOLIDATE | Machine becomes sole durable transition kernel |
| execution/workflow | KEEP semantics, MERGE durability | UMM becomes Machine-hosted interpreter |
| execution/operation | KEEP authority | operation lifecycle/effect certainty binding |
| execution/command | FACET | immutable command intent feeding Machine/Operation |
| execution/admission | KEEP authority/policy boundary | no duplicate physical resource scheduler |
| execution/scheduling | POLICY | ordering/fairness only |
| experimentation | KEEP scientific semantics | compile to Machine invocations, remove loops |
| participant | KEEP contracts | agent loop becomes method/reference composition |
| environment | KEEP generic ABI | provider-specific cognition/task semantics move out |
| model | KEEP reproducibility semantics | package/serving mechanics delegate to providers |
| artifact/content | KEEP authority | absorb duplicate CAS stores |
| data | KEEP facts/source cuts | delegate analytic/vector execution |
| resource | KEEP authority | one lease/fencing lifecycle |
| runtime | KEEP infrastructure lifecycle | never duplicate Research Run truth |
| reliability/effect | KEEP authority | single external-effect certainty model |
| reliability/forensics | CONVERT toward evidence materialization | indexes/projections disposable |
| governance | SPLIT | executable policy stays; repo analysis becomes tools/gates |
| observability | ADAPTER/PROJECTION | semantic context retained, transport/storage delegated |
| operator | PRODUCT SURFACE | remove from authority topology |
| scope | CONSOLIDATE | one hierarchy authority; leaves become facets |
| portfolio | CONSOLIDATE | one metadata/manifest authority; leaves become facets |
## 23. Machine-readable disposition matrix

A generated architecture artifact must cover **every currently registered catalog node** exactly once. Each row must contain:

```text
path
current_authority
node_kind
disposition = KEEP | CONSOLIDATE | FACET | PROJECTION | PROVIDER | ADAPTER | POLICY | TOOL | PRODUCT_SURFACE | REMOVE
canonical_authority
reason
migration_target
```

Rules:

- no current catalog node may be absent;
- no row may have an empty disposition or canonical authority target;
- an `authority` row must satisfy the authority qualification test;
- non-authority rows must identify the authority they depend on or project from;
- provider/tool/product nodes may have `canonical_authority = external/non_authoritative` where appropriate;
- the matrix is generated from the live catalog plus explicit classification rules and is checked in CI;
- catalog edits that add a node without a disposition classification fail the architecture gate.

The matrix is a migration control plane, not permanent runtime state. Once migration completes, the canonical registry itself carries only retained authorities and explicit non-authority topology metadata where useful.

## 24. Catalog schema gate

The next System Registry schema must distinguish topology from authority. At minimum every node declares `node_kind`, and authorities additionally declare durability/effect/state characteristics.

The registry must not infer authority from package existence, directory depth, or the presence of a four-plane `api/runtime/providers/composition` layout.
## 25. Migration execution order

This is a dependency order, not a set of optional phases. Work continues through the sequence until the architecture converges.

1. Add node-kind/disposition metadata and architecture gates without changing runtime behavior.
2. Make Machine Journal the only durable scientific transition truth; refine the UMM adapter from whole-run wrapping toward node-level transitions.
3. Remove/redirect independent experimentation and Agent loops to Method/Machine execution.
4. Collapse duplicate checkpoint/progress/run truth into Machine-backed state and verified snapshots.
5. Unify content-addressed storage behind Artifact/Content ports; migrate model/kernel-local CAS users.
6. Unify resource lease/fencing semantics for compute, endpoint and recovery ownership.
7. Contract Scope and Portfolio leaf systems into facets of their root authorities.
8. Reclassify Operator and repository governance analyzers outside runtime authority topology.
9. Separate Environment providers from benchmark/method semantics, beginning with Minecraft as the stress test.
10. Reduce model qualification to requirement/evidence contracts and push installation/backend mechanics behind providers.
11. Convert Forensics toward evidence materialization/projection over primary authorities.
12. Delegate observability/query/storage mechanics while preserving Noetrium research correlation semantics.
13. Rebuild the canonical registry from retained authorities and validated non-authority topology.
14. Run full architecture/public-facade/schema/registry tests plus reproduction smoke tests.

## 26. Hard migration invariants

- No dual authoritative write path during migration.
- No silent fallback from new authority to legacy authority.
- No compatibility alias that permits downstream code to depend on a removed private authority.
- No physical host/GPU identity in scientific `ResourcePolicy` digest.
- No provider-specific package graph in platform scientific identity unless frozen as explicit provenance.
- No model-facing history projection may mutate host/Journaling truth.
- No benchmark scoring or paper-specific method semantics may move upstream solely for convenience.
- No new language or external system may become an authority merely because it executes a provider operation.
- All irreversible external effects require explicit intent/certainty/reconciliation semantics.
## 27. Acceptance criteria

Architecture convergence is complete only when all of the following hold:

- every live catalog node has an explicit kind and disposition;
- no thin re-export/view/provider leaf is registered as an authority without passing the qualification test;
- method node progress, interrupt and resume can be reconstructed from Machine-committed history plus verified snapshots;
- there is no platform-level hard-coded Agent loop competing with Method/Machine execution;
- experimentation workload/runner code does not own paper-generic `observe/recall/plan/act` truth;
- one immutable content authority serves artifact/model/checkpoint/dataset/evidence blob references;
- one resource lease/fencing model is reused across compute, endpoint and recovery ownership;
- Scope hierarchy has one mutation authority;
- Portfolio workspace/program/project metadata has one mutation authority;
- repository AST/complexity/import analysis is outside runtime authority topology;
- Operator surfaces mutate only through domain authority ports;
- provider-specific environment cognition/policy is downstream/reference code;
- Forensics indexes can be deleted and rebuilt without loss of primary business/scientific truth;
- query/analytics providers consume pinned source cuts and cannot mutate source authority;
- full test suite and architecture gates pass from a clean checkout.

## 28. Research-platform quality criterion

The architecture is successful only if adding a new paper normally requires implementing paper semantics and thin benchmark/provider adapters, not rebuilding execution, checkpointing, evidence, resource scheduling, model serving, tracing, retry, recovery or experiment infrastructure.

Conversely, Noetrium must not absorb paper semantics merely to make one reproduction shorter. A mechanism is promoted upstream only after it is demonstrably reusable and method-independent.

This specification therefore optimizes the quantity that matters most for Noetrium: **scientifically faithful research iteration throughput per unit of downstream implementation complexity**, while retaining exact reproducibility, recoverability and authority integrity.
## 29. Audit evidence captured by this specification

The migration is based on concrete repository evidence rather than naming preference:

- `portfolio/project/api/contracts.py` explicitly re-exports the root Portfolio contracts and states that it does not create a competing authority.
- `scope/identity`, `scope/hierarchy`, `scope/membership`, `scope/ownership` and `scope/resolution` are thin leaf-owner/provider wrappers around a root Scope registry.
- `operator/runtime/run_control_application.py` explicitly describes itself as a translation layer over Run Control authority.
- `governance/architecture` contains large repository/source analyzers such as budget/import/source profiling rather than runtime domain state.
- `experimentation/workload/runtime/phases.py` implements a generic agent cycle independent of UMM/Machine execution.
- `experimentation/study/runtime/matrix.py` composes its own runner/lifecycle/metric/observation machinery.
- `capabilities/participant/agent/runtime/cognition_loop.py` is another generic agent-loop implementation.
- the former `research/execution/workflow/runtime/machine_adapter.py` whole-run adapter was identified as a competing coarse truth path and removed after node-level Machine authority tests passed.
- `foundation/kernel/kernel/machine.py` already provides the stronger durable transition model that should host method-node truth.
- Minecraft composition currently mixes environment I/O with planning, recipes, skills, task completion, combat and cognition policy.
- formal Artifact content storage coexists with model-request and kernel-local content-addressed stores.
- generic ResourceLease coexists with endpoint-specific and compute-specific TTL/fencing lifecycles.
- recovery maintains another independent lease implementation.
- semantic retrieval performs platform-local cosine/L2 execution rather than delegating query mechanics.
- Forensics correctly distinguishes authoritative ledgers from disposable indexes, providing a foundation for evidence-materialization convergence.

These observations are the baseline against which the refactor is verified.