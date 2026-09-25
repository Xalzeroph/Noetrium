# Current Development Baseline

**Baseline date:** 2026-09-19
**Platform version:** 0.44.0
**Repository role:** reusable upstream Research Agent OS platform
**Architecture baseline that initiated this consolidation pass:** `6369f8f0e5310ce470db0557d1218ed6fef546a6`

This document records the current development interpretation of the generic Noetrium repository. It is not release evidence and it does not override the architecture authority order in [`../architecture/CURRENT_ARCHITECTURE_AUTHORITY.md`](../architecture/CURRENT_ARCHITECTURE_AUTHORITY.md).

Concrete research methods, benchmark tasks, project-specific scientific semantics, project model selections, machine inventories, experiment matrices, and scientific results are downstream-owned. Reusable first-party contracts, providers, reference implementations, execution/evidence mechanisms, and research infrastructure may remain upstream when they are generic across projects.

## Current architecture baseline

The platform is now interpreted as an **authority-shaped Research Agent OS**, not as one independent authority per registered package or recursive system leaf.

The current architecture precedence is:

1. the canonical system registry is the live topology source;
2. `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md` is the normative authority-classification and execution-truth specification;
3. `UNIVERSAL_RESEARCH_MACHINE_ARCHITECTURE_20260919.md` is normative for paper-programmable Machine domains, the shared ResearchProgram host/interpreter model, Runtime modularity, and nested Machine composition;
4. `AUTHORITY_DISPOSITION_MATRIX_20260916.json` plus executable checks define machine-verifiable node disposition;
5. `NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md` remains the long-form end-state rationale and defers programmable-Machine details to the 2026-09-19 specification;
6. generated maps, catalogs, schemas, status reports, and release files are evidence only for the exact source cut they name.

The 2026-09-16 consolidation supersedes the old fine-grained rule that many catalog leaves should each be interpreted as a state authority. Registered nodes may instead be authorities, facets, projections, providers, adapters, policies, tools, or product surfaces.

## Execution truth

The canonical scientific-execution invariant is:

> Any change to scientific execution truth is authoritative only after acceptance through the owning Machine/effect/evidence authority.

`MachineExecutor` and the Machine Journal own accepted Machine transition history. UMM remains the universal research-method interpreter and must not become a second durability authority. `MachineMethodTransitionAuthority` binds method-node truth into the Machine executor.

Checkpoints and snapshots are recovery acceleration artifacts bound to accepted execution cuts. They are not independent mutable histories. Agent cognition loops, experiment runners, workload loops, and provider runtimes may compute or orchestrate work, but they do not become competing execution authorities merely because they contain loops or mutable implementation state.

Resource admission, physical compute scheduling/placement, fencing/leases, and provider runtime state remain outside Machine transition authority and are composed through their owning typed boundaries. Paper-variable logical participant scheduling is different: when it changes scientific execution order, it is RuntimeProgram semantics and its accepted decisions are journal-backed.

## 2026-09-19 programmable Research Machine convergence

The active convergence tranche has collapsed paper-variable execution onto one Machine kernel instead of adding domain-specific runners.

- Method remains the specialized `MethodProgram` + UMM interpreter path, but accepted transitions still commit through `MachineExecutor` and the Machine Journal.
- Runtime, Participant, Environment, Memory, Evaluation, Optimization, Experiment, and Research Run use the shared `ResearchProgram` / `ProgrammableMachineInterpreter` / `ResearchProgramHost` substrate.
- Runtime concern-local semantics are composed as `RuntimeModule` values into one frozen RuntimeProgram rather than acquiring separate journals.
- Context projection remains a pure `ContextProgram` sub-IR; a studied context policy is identity-bound from the enclosing RuntimeMachine.
- Capability mediation, model invocation, communication, logical participant scheduling, synchronization/barriers, recovery/intervention, and visibility now have reusable Runtime semantics rather than fixed Agent-loop ownership.
- Program handlers, host operations, context renderers, capability mediators, model request/response policies, logical schedulers, synchronization deciders, recovery/intervention policies, visibility deciders, and trial operations bind explicit implementation digests so changing executable semantics changes reproducibility identity rather than silently changing behavior.
- Runtime synchronization now distinguishes paper-variable logical coordination from physical scheduling: asynchronous release, barriers and quorum gates are RuntimeProgram semantics, while worker/process/resource scheduling remains infrastructure.
- Trial and matrix execution are Program-backed; opaque Python trial/matrix extension loops are no longer the canonical scientific control-flow surface.

This is intentionally a small-family design. A new paper-variable concern should first be expressed as a Program, RuntimeModule, rule set, pure sub-IR, or injected operation handler. A new Machine domain is justified only when it needs an independently durable scientific identity and transition history.

## Repository boundary

The reusable package boundary is `noetrium_platform/` plus the root-level `components/` and `orchestration/` reference/extension layers. The `noetrium/` package exposes narrow public contracts and platform facades.

The upstream must remain buildable and testable without downstream project source. The enforceable split contract is [`../architecture/DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md`](../architecture/DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md) together with `scripts/platform_repository_boundary.py`.

A downstream project may add paper methods, benchmark adapters, scientific policies, specialized evaluators, model profiles, deployment inventory, and application surfaces through public typed contracts. It must not require the upstream platform to import or name the project.

## Downstream method contract

Noetrium supports two complementary research-authoring paths:

- component-level research replaces a planner, memory policy, model policy, environment adapter, tool policy, evaluator, or other reusable seam;
- whole-method research supplies a typed `ResearchMethodProgram` / `MethodProgram` control graph.

In both cases, the downstream project owns the novel scientific semantics. The platform owns the reusable mechanics around run identity, frozen bindings, Machine execution, capability/effect boundaries, recovery, evidence, artifacts, resource admission, observability, experiment matrices, and common research-analysis/publication infrastructure.

The public generated facade/catalog path remains the preferred downstream import boundary. Generated discovery is read-only metadata and must not become a runtime service locator.

## Generated architecture evidence

At the start of this consolidation pass, the checked-in source-derived architecture maps still identified source cut `3d1ecac8b128fe6587433e9d7f829919121f88ee`. That mismatch was one of the reasons to add an explicit regeneration closure.

At that historical generated cut, `CODE_ARCHITECTURE_MAP.md` reported:

- 2,491 Python modules;
- 2,969 classes;
- 5,206 module-import edges;
- 173 registry nodes;
- 22 registry authorities;
- 0 parse errors.

`REPOSITORY_CODE_ARCHITECTURE_MAP.md` reported:

- 3,657 tracked files;
- 3,380 Python files;
- 4,008 symbols;
- 8,044 Python import edges;
- 0 parse errors.

Those values are retained as historical source-cut evidence only. After regeneration, always use the source revision and counts embedded in the newly generated artifacts rather than copying the values above forward.

## Validation status

The previous 2026-09-05 baseline contained exact test and architecture counts for that historical source tree. Those numbers are no longer presented as current validation results.

The architecture-changing source cut `6369f8f0e5310ce470db0557d1218ed6fef546a6` was the reviewed consolidation tip before this documentation pass and carried the commit purpose `fix(architecture): verify consolidation against live tests`.

The current CI closure is source-cut specific. It compiles source, runs the full Python suite on Python 3.11 and 3.12, verifies test taxonomy, benchmark/reproduction catalogs, public contracts, project-design trace rejection, generated downstream/architecture projections, README localization, no-degradation constraints, and then qualifies the exact built distribution/container. Canonical projections are regenerated from the latest mainline cut with a lease so an older projection job cannot overwrite a newer source cut.

Exact current full-suite, architecture, algorithm, concurrency, performance, packaging, and release counts must still be regenerated from the final consolidated source cut before a release or paper provenance record may claim them.

The rule is strict: historical release files and historical status counts remain evidence for their own source tree only. Source changes invalidate reuse of those values as current truth.

## Provider and environment baseline

Minecraft remains a reusable bundled environment provider, while benchmark scoring, task success semantics, skills, planning, memory, combat policy, and cognition remain downstream Method/Benchmark responsibilities unless separately justified as generic platform contracts.

The provider boundary should prefer locked native Mineflayer capabilities for world interaction and navigation while Noetrium owns typed action identity, effect verification/reconciliation, and provenance at the platform boundary. Generic environment contracts must remain provider-neutral.

Model, environment, runtime, compute, storage, and vendor-specific mutable implementation state becomes research truth only through the corresponding frozen binding, accepted authority record, effect receipt, evidence record, or immutable source cut.

## Packaging and deployment

The generic Docker image stays lightweight. Environment-specific overlays such as Minecraft may add Java/Node/native runtime dependencies without forcing them into every platform deployment.

A release is authoritative only when the release subsystem regenerates its manifests/evidence from the exact final source tree and all required architecture, repository-boundary, contract, regression, packaging, and release gates pass. `RELEASE_MANIFEST.json` is the canonical frozen release-manifest artifact and `RELEASE_EVIDENCE.json` is the canonical frozen release-evidence artifact for that exact release source cut; this development baseline never substitutes for either. A historical image digest, doctor result, package manifest, or release-evidence record must not be reused as proof for a later source cut.

## Immediate consolidation work

Before treating the current tree as documentation-complete, the following must remain synchronized:

- documentation authority order and supersession notices;
- system-registry node kinds and disposition validation;
- generated downstream capability catalog and interface schema;
- generated source/repository architecture maps;
- researcher quickstarts describing UMM as the method interpreter rather than a second execution kernel;
- single-mainline development documentation;
- exact validation and release evidence for the final source cut.

The target is not fewer files for its own sake. The target is one unambiguous owner for every durable or scientific truth, with downstream paper development reduced to the genuinely novel method semantics.
