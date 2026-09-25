# Current Architecture Authority

> Status: **Current documentation authority map**
> Effective date: 2026-09-19
> Architecture baseline that initiated this consolidation pass: `6369f8f0e5310ce470db0557d1218ed6fef546a6`

This document defines how Noetrium architecture documents are to be interpreted when historical designs, generated topology mirrors, and current normative specifications overlap. It does not create a second runtime authority. It only establishes documentation precedence.

## 1. Authority order

Use the following order when two documents appear to disagree.

1. `noetrium_platform/foundation/governance/system_registry/catalog.json` is the live source of registered topology and node metadata.
2. `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md` is the normative authority-classification and execution-truth specification.
3. `UNIVERSAL_RESEARCH_MACHINE_ARCHITECTURE_20260919.md` is the normative authority for paper-programmable Machine domains, Program/Rule/Host semantics, Runtime modularity, and nested research-Machine composition.
4. `AUTHORITY_DISPOSITION_MATRIX_20260916.json` and its executable migration/validation code define the machine-checkable disposition of registered nodes into authority, facet, projection, provider, adapter, policy, tool, or product surface.
5. `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md` is the long-form Research OS design history and end-state rationale. Its 2026-09-19 supersession notice defers Machine-family details to item 3.
6. Generated architecture maps and catalogs describe a particular source cut. They are evidence about implementation structure, not normative architecture by themselves.
7. Specialized design, audit, quickstart, benchmark, provider, and downstream documents apply only within the boundary they own and must conform to items 1–6.
8. `status/` and `history/` documents are source-cut reports or historical evidence. They never override a newer normative contract.

## 2. Supersession rules

The 2026-09-16 authority-consolidation specification explicitly supersedes, for authority classification:

- `VNEXT_DETAILED_SYSTEM_MAP.md`;
- `VNEXT_SYSTEM_CATALOG.json`;
- the fine-grained system-decomposition portions of `REFACTORING_VNEXT_DESIGN.md`.

Those files remain useful for historical responsibility decomposition and migration context, but their old rule that many recursive leaves should be treated as independent authorities is no longer current.

The 2026-09-16 specification preserves and sharpens `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md`. In particular:

- `MachineExecutor` plus the Machine Journal is the acceptance boundary for scientific execution truth;
- UMM remains the universal research-method interpreter and is not a second durability authority;
- checkpoints are verified acceleration artifacts bound to an accepted journal cut, not a competing state history;
- paper-variable execution loops are expressed as RuntimeProgram/ParticipantProgram/other programmable Machine Programs; provider mechanics and projections remain outside Machine authority unless they independently pass the authority qualification test;
- resource admission, physical resource scheduling/placement, and leases remain outside Machine state-transition authority; paper-variable logical participant scheduling belongs to RuntimeProgram semantics when it changes scientific execution order;
- providers and vendor integrations implement typed ports but do not become platform authorities merely because they own mutable implementation state.

## 3. Topology versus authority

A registered node is not automatically an authority.

The registry may retain fine-grained nodes for discoverability, ownership, generated facades, dependency validation, and documentation. Each node must nevertheless have a semantic kind. Only an `authority` may accept or mutate authoritative truth.

The required interpretation is therefore:

```text
canonical registry
    -> topology and ownership metadata

normative consolidation spec + disposition matrix
    -> authority classification

source-derived architecture maps
    -> implementation evidence for an exact Git cut
```

Do not infer authority from directory depth, package count, class names, generated facade count, or the existence of a store/registry/provider implementation.

## 4. Current execution model

The current Research OS execution model is:

```text
Study / Experiment / Run scientific intent
                 |
                 v
 MethodProgram / ResearchProgram
       programmable semantics
                 |
                 v
      UMM / Program interpreter
                 |
                 v
          MachineCommand
                 |
                 v
          MachineExecutor
                 |
                 v
       Machine Journal commit
                 |
       +---------+----------+
       |         |          |
       v         v          v
   operation   effect    artifact/evidence
   authority   authority  authorities/facts
```

External model, environment, runtime, compute, resource, storage, and vendor implementations remain typed provider boundaries. Their observations or receipts become research truth only through the owning authority and accepted transition/evidence path.

## 5. Method-author contract

A downstream paper should implement only the scientific semantics that are actually novel.

Typical downstream-owned concerns include method control logic, planner/search/reflection policy, task-specific memory semantics, benchmark adapters, domain-specific completion criteria, model policy, environment-specific scientific interpretation, and specialized evaluation logic.

The platform should provide the reusable mechanics: run identity and frozen bindings, typed capabilities, model/environment/runtime provider seams, Machine execution, effect certainty, checkpoints/recovery, evidence and artifacts, resource admission, observability, experiment matrices, and common analysis/publication infrastructure.

A convenience abstraction must not be promoted into a new authority merely to reduce downstream code. Conversely, downstream projects should not reimplement an upstream authority when a public typed contract already exists.

## 6. Generated-document rule

Generated documents must state or cryptographically bind the exact source Git revision/digest from which they were produced. They are stale as soon as the source tree changes in a way that affects their generator inputs.

At the start of this consolidation pass, `CODE_ARCHITECTURE_MAP.md` and `REPOSITORY_CODE_ARCHITECTURE_MAP.md` still identified source cut `3d1ecac8b128fe6587433e9d7f829919121f88ee`. That mismatch is historical evidence of the drift this pass is closing; it is not a permanent statement about the maps. Always inspect the generated artifact's own source header/digest before treating it as current.

The same rule applies to generated capability catalogs, interface schemas, topology mirrors, quality reports, release evidence, and benchmark snapshots.

## 7. Regeneration and verification closure

Architecture-changing source or authority-document changes must converge through the repository authority-consolidation CI closure. That closure:

1. applies the current authority/dependency consolidation migration idempotently;
2. regenerates downstream contracts and generated documentation;
3. regenerates core and whole-repository code architecture maps;
4. runs source compilation, test-system checks, public-contract audit, registered-surface audit, and generated-doc drift checks;
5. runs focused authority/disposition/topology tests plus Method-to-Machine journal and downstream-contract tests;
6. commits deterministic generated drift back to `main` only after those checks pass.

A bot-generated refresh does not create new architecture semantics. It materializes deterministic projections of the canonical source cut.

If the source tree advances while an older regeneration job is running, that older job must not overwrite the newer mainline. The closure must be rerun from the new tip so generated source identity and tested source identity converge.

## 8. Historical-document rule

Historical design text is preserved when useful for rationale and migration evidence. It must not silently masquerade as current authority.

A historical document that contains a superseded architectural claim should either:

- carry a visible supersession notice near its title; or
- be linked from this document with an explicit historical/superseded classification.

Do not rewrite published history merely to make it look as if the current design always existed.

## 9. Current reading path

For architecture work, read in this order:

1. `CURRENT_ARCHITECTURE_AUTHORITY.md`;
2. `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`;
3. `UNIVERSAL_RESEARCH_MACHINE_ARCHITECTURE_20260919.md` for programmable Machine/Runtime semantics;
4. the latest supersession sections of `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md`;
5. the live system registry and `AUTHORITY_DISPOSITION_MATRIX_20260916.json`;
6. regenerated source-derived architecture maps for the exact working source cut;
7. the specialized design document for the subsystem being changed.

For downstream paper work, start from the public generated contracts and the relevant researcher/provider guide, but interpret every runtime/durability claim through the same authority order above.

## 10. 2026-09-19 universal research-machine authority

`UNIVERSAL_RESEARCH_MACHINE_ARCHITECTURE_20260919.md` is normative for
research-programmable execution surfaces. It supersedes older fixed Machine
family descriptions. It does not change Machine Journal truth ownership.

The kernel coordinator is `MachineExecutor`. `Runtime` now exclusively means
paper-programmable research execution semantics; process/service/host lifecycle
is infrastructure.


## 11. Runtime modularity

Runtime is a paper-programmable Machine domain, not process/service
infrastructure. A monolithic custom runner is not the preferred downstream
extension seam.

Concern-local execution semantics are authored as `RuntimeModule` values and
composed with `RuntimeProgramComposer` into one journal-backed RuntimeProgram.
Current concern vocabulary includes turn/event, context, communication,
logical scheduling, synchronization, capability mediation, visibility,
recovery and intervention. Replacing one module changes the frozen RuntimeProgram identity
without creating a new authority or a second runtime history.

Concrete reusable Runtime semantics now include pure/context projection,
journal-backed communication, Machine-backed capability mediation, programmable
model invocation, programmable logical participant scheduling, journal-backed
synchronization/barriers, recovery/intervention, and programmable visibility. Policy
implementations that can change paper behavior carry explicit implementation
identity; their digests participate in the frozen program/binding identity.
Runtime owns journaled paper-variable decisions while effect reconciliation,
rollback/restart I/O, transport, physical scheduling and resource placement
remain mechanics behind typed provider/authority boundaries.


## 12. Final programmable Machine family

The research-programmable surface is intentionally small.

- Method: `MethodProgram` interpreted by UMM.
- Runtime: `ResearchProgram(kind=runtime)`.
- Participant: `ResearchProgram(kind=participant)`.
- Environment: `ResearchProgram(kind=environment)`.
- Memory: `ResearchProgram(kind=memory)`.
- Evaluation: `ResearchProgram(kind=evaluation)`.
- Optimization: `ResearchProgram(kind=optimization)`.
- Experiment: `ResearchProgram(kind=experiment)`.
- Research Run: `ResearchProgram(kind=run)`.

All non-Method domains share `ResearchProgram`, `ProgrammableMachineInterpreter`,
`ResearchMachineSession`, `ResearchProgramHost`, `MachineExecutor`, and the
Machine Journal. Event-driven domains reuse the domain-neutral
`MachineEvent / ProgramRule / ProgramRuleSet` layer rather than defining a
domain-specific runner.

Nested research work is explicit. `ChildResearchMachineExecutor` executes a
child through `ResearchProgramHost`; the parent commits a typed
`ChildMachineLink` to the exact child Machine cut. Method/UMM uses the same
link contract. A supervisor coordinates lifecycle only and cannot become a
second parent/child truth ledger.

The following are not programmable Machine domains merely because they are
complex: Model, Artifact, Evidence, Data, Metrics, Observability, Scope,
Portfolio, physical resource scheduling, process/service lifecycle, and pure
policy. Their reusable mechanics remain authorities, providers, facets,
projections, or pure functions according to the authority-classification spec.
