# Documentation Index

This directory is the single documentation root for the reusable Noetrium. Documents are grouped by platform ownership and lifecycle; downstream research repositories own their own methods, tasks, project-specific environment compositions, deployment inventories, and result documentation. Reusable first-party providers may remain upstream.

## Authority order

Read [`architecture/CURRENT_ARCHITECTURE_AUTHORITY.md`](architecture/CURRENT_ARCHITECTURE_AUTHORITY.md) first whenever architecture documents overlap or disagree. The current order is:

1. `noetrium_platform/foundation/governance/system_registry/catalog.json` is the unique live topology and registered-node metadata source.
2. [`architecture/NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`](architecture/NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md) is the normative authority-classification and execution-truth specification.
3. `architecture/AUTHORITY_DISPOSITION_MATRIX_20260916.json` and its executable validation/migration code provide the machine-checkable node dispositions.
4. [`architecture/NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md`](architecture/NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md) is the long-form Research OS end-state design; later supersession sections inside it override earlier historical sections.
5. `architecture/VNEXT_SYSTEM_CATALOG.json`, downstream capability catalogs, interface schemas, code maps, quality reports, and other generated documents are source-cut mirrors/evidence. They do not create an independent authority and are current only for the exact Git source cut from which they were generated.
6. Current architecture, infrastructure, governance, quickstart, audit, and provider documents describe their owned reusable boundary and must conform to the order above.
7. `status/` reports source-cut development state; `history/` preserves engineering history. Neither overrides a newer normative contract.

The 2026-09-16 consolidation specification explicitly supersedes, for authority classification, `VNEXT_DETAILED_SYSTEM_MAP.md`, `VNEXT_SYSTEM_CATALOG.json`, and the fine-grained system-decomposition portions of `REFACTORING_VNEXT_DESIGN.md`. Those files remain useful as historical decomposition and migration evidence.

A downstream repository may add project-local documentation, but it is not part of the upstream platform authority.

## Documentation hierarchy

- [`architecture/`](architecture/README.md) — recursive platform architecture, authority topology, composition, data flow, repository boundaries, generated source maps, and migration contracts.
- [`architecture/CURRENT_ARCHITECTURE_AUTHORITY.md`](architecture/CURRENT_ARCHITECTURE_AUTHORITY.md) — current documentation precedence, supersession rules, and the authoritative reading path.
- [`COMPONENT_LAYERS.md`](architecture/COMPONENT_LAYERS.md) — reusable single-agent components and higher-tier multi-agent orchestration.
- [`DIRECTORY_ARCHITECTURE_V2.md`](architecture/DIRECTORY_ARCHITECTURE_V2.md) — semantic package planes, component tiers, and dependency direction.
- [`infrastructure/`](infrastructure/README.md) — reusable model, runtime, server, observability, storage, and execution infrastructure.
- [`governance/`](governance/README.md) — architecture gates, forensic evidence, debugging policy, no-degradation rules, and documentation policy.
- [`status/`](status/README.md) — current source-cut baseline and generated governance reports.
- [`history/`](history/README.md) — immutable platform engineering milestones.
- [`readme/`](readme/README.md) — multilingual README registry, section schema, translation freshness, terminology, and release gate policy.

## Repository split contract

The upstream repository contains only reusable platform code and first-party generic infrastructure. Concrete research projects belong in downstream repositories that either depend on or fork the platform.

See [`architecture/DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md`](architecture/DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md) for the supported fork/update model and [`architecture/GENERIC_PLATFORM_BOUNDARY.md`](architecture/GENERIC_PLATFORM_BOUNDARY.md) for dependency direction.

## Current status

[`status/CURRENT_DEVELOPMENT_BASELINE.md`](status/CURRENT_DEVELOPMENT_BASELINE.md) records the current development source cut and known validation state. Generated algorithm, concurrency, performance, code-architecture, release, and other evidence is authoritative only for the exact source revision recorded by the artifact itself. Historical validation counts must not be reused as current results after the source tree changes.

Documentation changes are governed by [`governance/DOCUMENTATION_CHANGE_POLICY.md`](governance/DOCUMENTATION_CHANGE_POLICY.md). Implementation, tests, generated artifacts, and owning documentation are expected to move together.

## Documentation rules

- Keep one canonical document per reusable platform contract.
- Distinguish topology, authority classification, provider implementation, projections, and product surfaces explicitly.
- Do not infer authority from package depth, class names, generated facade count, or the existence of a store/registry/provider implementation.
- Put reusable capability documentation under `infrastructure/`.
- Put platform ownership and dependency rules under `architecture/` or `governance/`.
- Put project-specific scientific material only in downstream repositories.
- Add a platform history note when a platform contract or implementation boundary materially changes.
- Mark superseded design text visibly rather than silently rewriting historical rationale.
- Root `README.md` and `CONTEXT.md` are navigation documents, not alternative authorities.