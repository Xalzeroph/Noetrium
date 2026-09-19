# Noetrium External Design Absorption Specification

> Status: **Normative engineering principle**
> Date: 2026-09-18
> Scope: external design research, capability promotion, implementation hygiene

## 1. Core rule

Noetrium may study mature external implementations, but project architecture is
never imported into the platform.

The only valid project-level absorption path is:

```text
external design evidence
→ semantic invariant
→ authority analysis
→ Noetrium-native contract
→ Noetrium-native implementation
→ focused proof
→ delete superseded duplicate mechanics
```

The implementation must look as if the capability had been designed inside
Noetrium from first principles.

## 2. Zero implementation-trace invariant

For a project, harness, framework, research platform, or application used as a
design source, production code must not retain its identity.

Forbidden in production implementation, public contracts, examples, canonical
architecture, generated public surfaces, or persistent scientific formats:

- source-project names in module, class, function, field, enum, operation, metric,
  configuration, or artifact identities;
- source-project object models or package hierarchy;
- project-specific compiler/bridge/adapter/facade layers;
- compatibility wrappers preserving the source project's API shape;
- source-project checkpoint, state, lifecycle, or authority model;
- opaque project invocation hosted as a permanent Noetrium execution node;
- source-project terminology when an equivalent Noetrium-native term exists.

External project identities belong only in isolated research audit material and
scientific reproductions whose fidelity explicitly requires source identity.

## 3. Libraries and protocols are different

A genuine library/package may be used directly when it is the strongest
implementation of a low-level mechanism and all of the following hold:

1. the library is an implementation detail, not an architectural authority;
2. its types do not cross Noetrium public contracts;
3. its names do not define Noetrium system/module/domain vocabulary;
4. scientific identity and durable state remain Noetrium-owned;
5. replacing the library does not change Noetrium semantics.

An external service or wire protocol may require an explicitly named operational
binding because the remote identity is materially real. That is service
integration, not project-design absorption. Such a binding must terminate at a
native Noetrium port and may not import the service provider's control plane or
state model.

## 4. Authority rule

Absorption transfers **semantics, never authority**.

A useful external design may improve authoring, scheduling, evaluation,
checkpoint triggering, participant roles, isolation, batching, admission,
reconciliation, or diagnostics. Accepted facts still belong to their existing
Noetrium authorities.

Examples:

- Machine Journal owns accepted scientific execution transitions;
- model binding receipts own exact selected model/deployment evidence;
- Study/Trial identity owns frozen scientific protocol;
- Artifact owns immutable content and placement identity;
- Effect owns external-effect certainty;
- checkpoint state is an accelerator bound to accepted execution cuts;
- projections, caches, logs, and metrics remain derived or side-plane state.

No external design can create a second writer for any of these.

## 5. Native vocabulary rule

Before implementation, every absorbed idea must be rewritten into Noetrium
vocabulary.

The design record must answer:

1. What invariant is actually useful?
2. Which Noetrium authority owns it?
3. Which existing contract should be extended or simplified?
4. Which implementation mechanics are generic and which are source-specific?
5. What can be deleted after absorption?
6. What proof demonstrates that the new native mechanism preserves or improves
   scientific correctness?

If the answer still requires naming the source project in the production API,
the design has not been absorbed deeply enough.

## 6. No adapter architecture

A whole-project adapter is prohibited.

Do not solve platform generality by accumulating:

```text
ProjectAAdapter
ProjectBAdapter
ProjectCCompiler
ProjectDCompatibilityLayer
...
```

That architecture scales linearly with other people's ecosystems and makes the
platform a compatibility shell.

Instead, identify the common semantic primitive and make that primitive native.
Different research methods should compile directly to Noetrium contracts, not
through foreign project abstractions.

## 7. Method-system rule

Noetrium has one method execution ABI: `MethodProgram`.

External project designs may inspire graph authoring, interrupt semantics,
role resolution, checkpoint trigger UX, or state projection, but platform code
must implement those ideas directly through native MethodGraph/MethodProgram/
Machine contracts.

A downstream reproduction of a paper or system recreates the scientific method
semantics natively. It does not embed the original framework runtime merely to
claim fidelity.

## 8. Experiment-system rule

Benchmark/task packaging, verifier isolation, participant separation, evaluation
rebinding, resource declarations, and run limits must be expressed as native
Study/Trial/Task/Participant contracts.

A benchmark package never owns the method being evaluated. A verifier never
receives undeclared execution-private state. A simulated user is a Participant,
not hidden Environment state.

These are Noetrium semantics regardless of where the design lessons originated.

## 9. Infrastructure rule

Scheduling, concurrency, telemetry, storage, query, model serving, lifecycle,
and process-control systems follow the same split:

- Noetrium owns semantic contracts, authority, identity, evidence, policy, and
  failure behavior;
- replaceable mechanics may use strong libraries privately;
- project control planes are not embedded;
- external mutable truth is never promoted into Noetrium authority merely
  because a mature system exposes it.

## 10. Promotion pipeline

Every project-level design absorption must pass these stages:

### A. Source audit
Record the external source, exact version/cut where relevant, observed semantic
behavior, and limitations in the isolated research-audit area.

### B. Semantic extraction
Describe the invariant without source-project terminology.

### C. Authority placement
Map each state transition and durable fact to an existing Noetrium authority.
If a new authority is proposed, prove that no existing authority can own it.

### D. Native design
Extend, merge, or simplify Noetrium contracts. Do not create a compatibility
layer.

### E. Differential proof
Where useful, compare the native mechanism against the audited behavior using
fixtures or reproductions, but keep source-project identity out of production
code.

### F. Contraction
Delete obsolete Noetrium duplicate mechanics and any temporary research bridge.

## 11. Backward compatibility

No forward architecture work is constrained by compatibility with retired
Noetrium APIs or earlier project-shaped integrations.

When the strongest native contract changes:

- update consumers;
- migrate reproductions;
- regenerate projections;
- delete retired compatibility code.

Do not retain aliases, adapter facades, dual paths, or duplicate authorities.

## 12. Mechanical enforcement

CI must reject external project design identities from production code roots.
The source identity list lives in isolated research-audit material; the gate is
generic and does not encode those projects into platform logic.

Protected roots include:

- `noetrium_platform/`
- `noetrium/`
- `components/`
- `orchestration/`
- `examples/`

Research reproductions and isolated external-design audits are outside this
production-code rule because source identity can be part of scientific
provenance there.

## 13. Acceptance criterion

An absorption is complete only when a reviewer can remove the external research
audit from view and the production architecture remains fully understandable.

The resulting capability must be explainable entirely in terms of Noetrium
semantics, authorities, contracts, evidence, and failure behavior.
