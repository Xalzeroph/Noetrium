# vNext System Blueprint

> **Historical decomposition / current interpretation notice (2026-09-17):** This document predates the authority-consolidation specification. Its hierarchy remains useful for responsibility decomposition and migration context, but a node shown here is **not automatically an independent authority**. Current authority classification is governed by `CURRENT_ARCHITECTURE_AUTHORITY.md`, `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`, the live system registry, and `AUTHORITY_DISPOSITION_MATRIX_20260916.json`.

## Architectural rule

The platform is designed top-down. A parent boundary owns only its direct responsibility and composes children through narrow contracts. Child boundaries never reach into parent implementation state.

```text
Platform
├── Scope
├── Portfolio
├── Experimentation
├── Execution
├── Participant
├── Scientific
├── Resource
├── Environment
├── Model
├── Runtime
├── Data
├── Artifact
├── Reliability
├── Observability
├── Governance
└── Operator
```

The tree above is a responsibility/topology view. Under the current authority model, some entries are authorities while others are facets, projections, providers, tools, or product surfaces.

## Ownership boundaries

| System | Owns | Must not own |
|---|---|---|
| Scope | hierarchy, ownership path, scope identity | project metadata, experiment semantics, runtime state |
| Portfolio | workspace/program/project metadata | study/run state, model state |
| Experimentation | study/trial/measurement/analysis/experiment/run/checkpoint semantics | server/process control and concrete participant/environment/model implementations |
| Execution | workflow/operation/capability orchestration | provider storage, scientific semantics |
| Participant | participant contracts/bindings/sessions | concrete server supervision, scientific state |
| Resource | resources, leases, compute inventory, directories | environment semantics, model deployment |
| Environment | environment specs/bindings/resolution/instances | project semantics, model selection |
| Model | model assets/stacks/assignments/deployments/serving identity | process lifecycle implementation |
| Runtime | servers/processes/services/sessions | experiment semantics, model catalog truth |
| Data | durable facts, records, datasets, canonical state, projections | immutable content storage identity |
| Artifact | immutable content and identity/reference | mutable business state |
| Reliability | effects, failures, recovery, forensics | scientific truth, UI views |
| Observability | logs, telemetry, status, observation projections | durable failure/state authority |
| Governance | architecture/release/quality/system topology rules | business execution |
| Operator | human query/command surfaces | domain authority |

These rows describe responsibility boundaries. They do not supersede the current disposition matrix when determining whether a boundary owns independent authoritative truth.

## Standard internal shape

Independently replaceable implementation boundaries generally follow:

```text
Boundary
├── api/             # identities, contracts, ports
├── runtime/         # orchestration only
├── providers/       # concrete implementation/backends
└── composition/     # external wiring only
```

This is a source/layout convention, not a requirement that every boundary become a registered authority. No API package owns workers, locks, persistence mutation, buffering, process control, or provider branching merely because it exports a contract.

## Historical migration order

The original vNext migration order was:

1. Establish the complete system graph and ownership metadata.
2. Establish child-system skeletons and authority declarations.
3. Establish debug/log/failure/diagnostic seams.
4. Migrate organizational ownership: Portfolio/Scope/Experimentation.
5. Migrate Environment, Model, Resource and Artifact boundaries.
6. Migrate Runtime and Execution orchestration.
7. Migrate Reliability and Observability implementations.
8. Migrate Operator and Governance surfaces.
9. Migrate participant and downstream research implementations behind Experimentation-owned Study/Trial contracts.
10. Delete obsolete historical boundaries instead of adapting them.

The current continuation is authority consolidation: retain useful contracts and package boundaries while folding nominal child authorities that do not pass the authority qualification test into their canonical owner.

## Debug hierarchy

All boundaries expose stable correlation coordinates rather than implementation-specific knowledge:

```text
platform
→ system/boundary
→ subsystem/facet
→ scope
→ operation
→ component
→ trace/span
→ state/effect/model/artifact reference
→ log/failure/evidence
```

This allows root-cause analysis at platform, project, run, operation and component level without coupling the debug system to a domain implementation. Observability and diagnostic projections remain read-side views unless explicitly qualified as an authority by the current normative specification.
