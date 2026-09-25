# Harness pattern adoption

## Validation-state note

This document records reusable runtime patterns absorbed from reviewed harness designs. Historical test counts and architecture-edge totals are evidence for the source cut that produced them, not permanent current-state claims.

An earlier development cut recorded **687 collected tests, 687 passed + 4 subtests**, with Architecture / Silent-Failure / No-Degradation gates passing and an architecture report containing **6 capability, 30 operation, and 12 event seam edges**. Those numbers are preserved only as historical evidence; current validation must come from regenerated reports/tests for the exact source revision under inspection.

Current architecture precedence is defined by `CURRENT_ARCHITECTURE_AUTHORITY.md` and the 2026-09-16 authority-consolidation specification.

This platform borrows a small set of runtime ideas from the reviewed DeepSeek Harness source without adopting Cordis or an "everything is a plugin" architecture.

## Adopted boundaries

### Reconstructable model requests

`model_request_api` defines the storage-neutral envelope and ports. The envelope freezes the full `ImmutableModelIdentity` rather than an opaque resume tuple. The model-request runtime stores the canonical request body, compiled prompt and tool-schema bundle in content-addressed storage where required before the request is considered model-visible. `PromptRequestBuildTransaction` requires a `ModelRequestRecorderPort`, verifies the visible body, and returns a body reconstructed from durable/reference-bound content rather than relying on a builder-owned object graph.

The invariant is:

```text
model-visible request semantics == reconstruct(recorded request semantics + frozen provider/source binding)
```

Provider serialization remains provider-owned; the platform must retain enough frozen provenance to explain the actual request under that provider contract.

### Scoped registrations

`scope_api` owns the lifecycle contract and the scope runtime implements hierarchical scope visibility, reversible registration handles, and quiescent disposal. A child lease against an inherited parent registration is counted against the relevant lifetime boundaries. Individual handles can quiescently retire one registration; concurrent scope disposal callers converge on the same terminal boundary. Agent-turn capability routes are owned by a decision-cycle scope and are disposed in `finally`, so temporary registrations cannot survive the scope that created them.

### Capability invocation pipeline

The capability invocation pipeline wraps routing/admission around the existing effect-safe execution path. The order is conceptually:

```text
monotonic guards / admission
→ approval when required
→ provider/effect-safe execution
→ post policies
→ authoritative effect/transition/evidence recording
```

A post-policy rejection after execution must preserve that execution may already have happened and therefore cannot be interpreted as retry-safe evidence.

The capability pipeline does not create a second effect authority. Effect certainty, reconciliation, and durable effect intent remain owned by the effect subsystem.

### Incremental projections

Projection contracts bind source identity/version, starting watermark, ending watermark and projected suffix/cut. Source rewind, source identity change, same-watermark identity drift or projector-version change fails closed and requires rebuild.

A projection checkpoint or index is disposable acceleration state, not an authority promotion.

### Record planes

Execution records preserve semantic separation rather than collapsing every event into one universal event type:

```text
AUTHORITATIVE / DURABLE FACT
    -> accepted by the owning authority and may participate in reconstruction/replay

LIVE INTERCEPTION
    -> affects current execution; durable/scientific change needs explicit authority acceptance

SIDE-PLANE OBSERVATION
    -> diagnostics/telemetry only; never primary operational/scientific authority
```

The current Machine-Journal execution model sharpens this boundary: method/agent execution truth becomes authoritative only through accepted Machine transitions and the owning effect/evidence paths.

### Durable facts and unknown extensions

Required durable facts fail closed when their semantics are unknown. Only extensions explicitly declared ignorable may be skipped by compatible readers. Version tolerance must never turn an unknown required semantic into success.

### Architecture graphs

Architecture reports and code maps may emit capability, operation/effect, event/observation, import, authority, source-invariant and structural graphs.

These graphs are generated evidence. Their numeric edge counts are valid only for the source cut from which they were generated. The graph layer must preserve registry `node_kind` and canonical-authority semantics so facets/providers/projections are not drawn as independent durable authorities.

## Deliberately not adopted

- Cordis is not a runtime dependency.
- Scientific method authority is not dynamically patchable through a plugin registry.
- Existing Machine, effect, failure, runtime-control, experiment and evidence truths are not collapsed into one universal event log.
- Plugin/provider dynamism never overrides treatment identity, scientific firewalls, resource admission, effect safety, authority ownership, or release reproducibility.
- A foreign agent loop, checkpoint store, event bus, scheduler, service locator, or provider lifecycle is not imported wholesale when Noetrium already has an owning authority/port.

## Adoption rule for future systems

External repositories are comparison and design inputs. Before absorbing a mechanism:

1. identify the Noetrium truth/authority that already owns the concern;
2. separate transferable mechanism from the external project's scientific/product assumptions;
3. implement the mechanism behind the existing typed boundary or justify a new boundary without creating a duplicate authority;
4. add focused semantic tests;
5. regenerate affected contracts/maps/evidence for the exact source cut;
6. remove staging/reference code that is not a deliberate first-party reproduction.

The objective is faster and more faithful downstream research iteration, not maximal framework feature count.