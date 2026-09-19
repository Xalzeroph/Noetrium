# Platform Architecture — Contract-Driven Noetrium

> Current interpretation: read `CURRENT_ARCHITECTURE_AUTHORITY.md` and `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md` first. This document describes reusable platform boundaries; package/plane boundaries are not automatically independent authorities.

## Goal

Provide a reusable research platform where scientific method, agent, environment, capability providers, persistence backends and runtime supervisors are independently replaceable without rewriting the surrounding execution truth, effect safety, evidence, recovery, release and observability systems.

The design preference is **small modules + narrow ports + one authority per durable/effect/scientific-truth domain + explicit composition roots**.

## Top-level planes

```text
Composition Root
├── Stable Contract Plane
│   ├── kernel / machine contracts
│   ├── participant / method / capability contracts
│   ├── model / environment / runtime / resource contracts
│   ├── effect / failure / evidence / artifact contracts
│   └── scope / experiment / run / data contracts
├── Runtime / Interpreter Plane
│   ├── MachineExecutor
│   ├── UMM / workflow interpreters
│   ├── run / experiment orchestration
│   └── provider-facing runtime adapters
├── Durable Truth / Evidence Plane
│   ├── Machine Journal
│   ├── effect intent / certainty / reconciliation
│   ├── run / experiment / identity authorities
│   ├── artifact / evidence / source-cut authorities
│   └── other explicitly qualified authorities
├── Side-Plane Observation
│   └── telemetry / diagnostics / logs / projections / operator views
└── Scientific Implementations
    └── downstream project methods / benchmark adapters / policies
```

A registered node may be an authority, facet, projection, provider, adapter, policy, tool, product surface, or other explicitly allowed kind. Directory shape never promotes a node into authority.

## Execution truth

Scientific method interpretation and authoritative execution are deliberately separated.

```text
MethodProgram / ExperimentPlan
        ↓
UMM / method interpreter
        ↓
node or control proposal
        ↓
MachineMethodTransitionAuthority
        ↓
MachineExecutor
        ↓
Machine Journal commit
```

A Python return value, worker-local state mutation, provider callback, or checkpoint write does not by itself become scientific execution truth. Accepted Machine transition history is owned by the Machine execution authority.

Checkpoints/snapshots accelerate recovery from an accepted execution cut; they do not form a competing state history. Agent loops, workflow loops, experiment runners, and workload loops may orchestrate or interpret work but must not duplicate Machine execution truth.

## Implementation vs runtime

A scientific/functional implementation is not itself a runtime supervisor or authority.

```text
Implementation identity
        +
Session/runtime identity
        +
Configuration identity
        +
Source / dependency / provider binding
        ↓
Frozen runtime binding
        ↓
Runtime endpoint/session/provider
```

Recovery-relevant identity must be bound explicitly. Changing a runtime/provider/backend in a way that affects recovery or scientific semantics cannot silently restore incompatible state.

## Record planes

The platform keeps semantically distinct planes rather than collapsing all events into one universal bus:

```text
AUTHORITATIVE FACT / TRANSITION
    accepted by the owning authority and usable for reconstruction,
    replay, effect certainty, or scientific proof

LIVE INTERCEPTION / CONTROL
    may affect current execution only;
    durable/scientific changes require explicit authoritative acceptance

SIDE-PLANE OBSERVATION
    telemetry, logging, diagnostics and read projections;
    failure must not mutate primary truth
```

The exact classification is owned by the relevant contracts, not inferred from the fact that a record was persisted somewhere.

## Reconstructable model-visible requests

The exact semantic request shown to a model is a reproducibility-sensitive fact.

```text
Prompt/method resolution
→ compile request semantics
→ freeze model/provider/source identities
→ persist canonical referenced content where required
→ create request envelope
→ verify model-visible representation
→ provider/model invocation
→ bind response provenance
```

The required invariant is that the recorded semantic request and frozen provenance are sufficient to explain what the model actually received under the declared provider codec/runtime contract.

Provider serialization details remain provider-owned. Scientific request identity must not be reconstructed from mutable provider state after the fact.

## Capability invocation

Capability policy and external-effect certainty are separate concerns.

```text
Scoped capability binding
→ admission / monotonic guards
→ approval when required
→ provider invocation
→ effect intent / receipt / certainty / reconciliation
→ owning transition/evidence acceptance
```

A post-policy rejection after execution must preserve the fact that execution may already have happened. `UNKNOWN` effect certainty is never converted into success or blind retry permission.

Composition-time capability binding canonicalizes stable contract identity rather than relying on declaration order or provider-local object identity.

## Scope/lifetime model

Temporary registrations and bindings are owned by explicit scopes rather than ambient global registries.

```text
Study / Experiment / Run scopes
└── Decision / Operation scope
    ├── temporary capability bindings
    ├── leases
    └── child scopes
```

Disposal must respect active leases and converge deterministically for concurrent callers. Temporary registrations cannot escape the scope that created them.

## Projection model

Derived read models are disposable and rebuildable.

```text
Authoritative source
→ source cut / watermark
→ projector
→ projection checkpoint/index
```

Rewind, source replacement, same-watermark identity drift or projector-version drift fails closed and requires rebuild. A projection never becomes authoritative merely because it is faster to query or persisted in a convenient database.

## Architecture report

Architecture analysis may report physical imports, package cycles, authority violations, source invariants, capability/provider-consumer graphs, operation/effect seams, event/observation graphs, and structural hotspots.

Any numeric architecture report is **source-cut evidence**. Older counts such as historical import-edge totals are not current facts after the tree changes. Current numbers must come from regenerated reports/maps that bind the exact source revision under inspection.

Analyzer internals may optimize parsing, indexing, graph traversal, or batching without changing the public finding semantics or silently weakening fail-closed source acquisition.

## System registry authority

`noetrium_platform/foundation/governance/system_registry/catalog.json` is the canonical live topology declaration source for registered identity, parentage, package ownership, node kind, canonical authority relation, shape, dependencies, capabilities, and components.

The registry does **not** imply that every node is an independent durable authority. Direct authority exists only when the node is explicitly classified as `authority` and satisfies the current qualification rules.

Generated mirrors and facades must preserve this distinction.

## Resource and runtime separation

Machine execution does not own CPU/GPU/RAM/token capacity, placement, scheduling fairness, admission, lease TTL, or host/runtime lifecycle merely because a Machine consumes those resources.

Resource/compute/runtime authorities or providers admit and bind execution first; Machine execution then advances scientific state through its own transition authority.

This separation allows local, cluster, Slurm, Kubernetes/Kueue, Ray, or other providers to change without redefining MethodProgram semantics or Machine Journal truth.

## Operator management boundary

Operator CLI/UI surfaces issue typed intents and queries over existing authorities. They are product surfaces, not a second domain authority.

A command route may invoke model/resource/environment/runtime/run-control owners, but the operator layer does not acquire their durable truth simply because it initiated the operation.

## Forensic and diagnostic boundary

Diagnostics correlate existing facts, effects, failures, traces, logs, artifacts, evidence and source identities. They are read-side projections unless a separately qualified forensic evidence authority explicitly owns immutable forensic facts.

UI/search/index convenience must never manufacture causal or scientific truth that the underlying authorities did not record.

## Non-negotiable boundaries

1. Cross-system code depends on public APIs/ports, not unrelated concrete implementation packages.
2. Composition roots are the only places allowed to assemble unrelated concrete providers.
3. Platform packages never import downstream scientific implementation types.
4. Method packages never own concrete host/process/provider supervision merely to execute a paper.
5. Model/runtime/provider identity changes cannot hide behind compatibility aliases.
6. Recovery cannot silently degrade model, revision, engine, environment, method, source, or other recovery-relevant identity.
7. External effects use explicit intent + certainty + reconciliation; `UNKNOWN` is never a blind retry.
8. Side-plane observer failure cannot alter primary scientific/operational truth.
9. UMM, Agent loops, workload loops and experiment runners cannot maintain a second durable execution history beside Machine Journal truth.
10. Generated topology/schema/code maps are evidence for exact source cuts and must be regenerated after relevant source change.
11. Release evidence is generated only after the exact source manifest and required gates agree.
12. Downstream paper semantics remain downstream unless a mechanism is genuinely reusable and can be absorbed without importing the paper's scientific claim into platform authority.

## Debug path

```text
Study → Experiment → Run → Machine → Transition / Operation → Component
     → ModelRequest / Environment action / Effect / State mutation
     → Failure / Evidence / Artifact
     → diagnostic and operator projections
```

A model decision can additionally be traced to the frozen method/program identity, semantic request, prompt/tool schema, model/provider binding, source cut, effect/evidence references, and accepted Machine transition that consumed its result.
