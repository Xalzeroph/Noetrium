# Architecture

Noetrium is research infrastructure for reproducible AI-agent experiments. Its architecture is built around a small public surface and explicit ownership of scientific and operational state.

## Public model

The supported Python API is:

```python
from noetrium import NoetriumUnit, run
```

`NoetriumUnit` is the recursive immutable carrier for research intent and references. `run` is the public execution operation. A project loaded from disk is converted to the same semantic root before execution.

No downstream project should need to construct internal schedulers, resource managers, model servers, environment lifecycles, journals, or evidence stores directly.

## Core execution path

The canonical flow is:

```text
immutable research root
        |
        v
validation and semantic compilation
        |
        v
binding and admission
        |
        v
ResearchProgram / Machine execution
        |
        v
accepted journal transitions
        |
        +--> external effects and receipts
        +--> artifacts and evidence
        +--> measurements and projections
        +--> recovery and replay proofs
```

Scientific domains may expose different authoring concepts, but state progression converges on one Machine execution model. No subsystem may create a second authoritative execution history merely for convenience.

## Authority model

Noetrium distinguishes immutable declarations from dynamic authorities.

- Research declarations describe what should be executed and how scientific behavior is defined.
- Machine execution accepts scientific state transitions.
- Effect handling owns certainty about external actions.
- Resource and runtime systems own physical admission, placement, leases, and lifecycle.
- Artifact, evidence, data, and measurement systems own their respective research facts.
- Observability projects state for operators and diagnostics; it does not become command authority.

The governing rule is one durable fact, one owner. Caches, indexes, status views, generated maps, and logs may be rebuilt; they do not silently outrank the authority that produced them.

## Research semantics and downstream ownership

Noetrium owns reusable execution infrastructure. A downstream research project owns the scientific novelty.

Typical downstream-owned semantics include:

- concrete research methods and comparison methods;
- prompts, policies, memory algorithms, and planning logic;
- benchmark builders, task assets, task splits, and success criteria;
- scientific model or environment requirements;
- experiment hypotheses, matrices, and analysis choices;
- paper-specific interpretation and claims.

Typical platform-owned mechanisms include:

- immutable identity and frozen bindings;
- durable Machine execution and recovery;
- participant and workload execution substrate;
- capability and external-effect handling;
- model/environment/provider integration;
- resource admission and physical lifecycle;
- artifacts, evidence, provenance, and measurements;
- observability, diagnostics, and release verification.

A reusable platform change should not encode the private semantics of one paper. Conversely, a downstream project should not reimplement platform ownership when an existing public contract already covers the mechanism.

## Programs, children, and concurrency

Executable research behavior is represented as programs interpreted by the shared Machine runtime. Nested work is explicit: child execution is linked back to its parent by durable identity and accepted cuts rather than hidden callback state.

Workload dependency graphs execute through a bounded ready frontier. Independent work can proceed concurrently, but concurrency never creates a second scientific truth. Scheduling decisions that are purely physical remain outside paper semantics; scheduling that changes the research algorithm must be represented in the research program itself.

## Effects and uncertainty

External actions are not inferred from exceptions or transport status alone. The logical path is:

```text
request
  -> authorized capability
  -> effect intent
  -> provider execution
  -> receipt / observed certainty
  -> reconciliation when required
  -> accepted scientific transition
```

An uncertain external action remains uncertain until its owning effect path can reconcile it. Retry policy must not convert uncertainty into an unearned success or failure claim.

## Recovery and replay

The durable Machine journal is the execution history. Checkpoints and snapshots are acceleration artifacts tied to accepted execution state; they are not competing histories.

Recovery must preserve the frozen scientific identity and prove which prior work can be reused. Exact replay, checkpoint recovery, and observational reproduction are different guarantees and must not be conflated.

## Resources and runtime

Physical execution concerns are isolated from scientific declarations. Resource authorities own compute, process, endpoint, container, environment-instance, and other physical lifecycles. Leases, fencing, and generation identity prevent a stale process from reclaiming resources after ownership has changed.

Performance optimizations must preserve semantics. Pooling, batching, caching, single-flight construction, warm reuse, and adaptive concurrency are valid only when exact identity, lifetime, effect certainty, and evidence remain intact.

## Data, artifacts, and evidence

Research outputs are authority-backed values rather than arbitrary labels over JSON. Artifact identity, evidence provenance, measurements, and retained data must bind to the exact research and execution identities that produced them.

A run-local directory may carry bytes, but it is not automatically the canonical identity or provenance authority for those bytes.

## Extension rules

Before adding a new subsystem, ask in this order:

1. Does the behavior vary by paper? If yes, it belongs in downstream scientific semantics.
2. Does an existing Noetrium owner already have this responsibility? If yes, extend that owner or its provider boundary.
3. Is this a reusable paper-independent mechanism required by multiple projects? If yes, add the smallest typed implementation in the correct platform layer.
4. Does the new state have genuinely independent canonical truth? Only then consider a new authority.

Avoid introducing a new Runner, Manager, Controller, journal, scheduler, or registry simply because a call site is inconvenient.

## Repository boundaries

- `noetrium/` — public Python surface.
- `noetrium_platform/` — internal platform implementation.
- `components/` and `orchestration/` — reusable supporting components where still applicable.
- `research/` — repository-owned reference/reproduction material, not the public downstream API.
- `deploy/` — deployment and runtime entrypoints.
- `scripts/` — generation, audits, release checks, and maintenance tools.
- `tests/` — executable contracts and regression coverage.

Generated architecture indexes under this directory are implementation evidence for the source cut that produced them. They do not create separate architecture authority.
