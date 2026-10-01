# Noetrium downstream capability catalog

This file documents internal system topology plus the single Product Research OS downstream surface.
Do not edit it manually; run python scripts/update_generated_docs.py.

## How downstream projects use Noetrium

1. Import only the unified noetrium.api Research OS surface.
2. Start from ResearchPortfolioBuilder; Program/Method/Memory DSLs are reached through that root.
3. Control live research through ResearchOS; lower platform APIs are composition-only internals.
4. Run python scripts/update_generated_docs.py after changing registry topology or the Product API.

Example:

    from noetrium import api

    portfolio = api.ResearchPortfolioBuilder("research")
    program = portfolio.program("paper")
    os = api.open_project(".")

- Registered systems: 31
- Public API modules: 1
- Public symbols: 2
- Registry digest: 08d68ed5eec97297020d8747da32973664283da1e23e84313f1599bffe99f0f1

## Capability domains

| Domain | Systems | API modules | Symbols |
| --- | ---: | ---: | ---: |
| artifact | 1 | 0 | 0 |
| data | 3 | 0 | 0 |
| environment | 6 | 0 | 0 |
| execution | 2 | 0 | 0 |
| experimentation | 1 | 0 | 0 |
| governance | 3 | 0 | 0 |
| model | 1 | 0 | 0 |
| observability | 2 | 0 | 0 |
| operator | 1 | 0 | 0 |
| participant | 1 | 0 | 0 |
| platform | 1 | 0 | 0 |
| portfolio | 1 | 0 | 0 |
| reliability | 3 | 0 | 0 |
| research_os | 1 | 1 | 2 |
| resource | 2 | 0 | 0 |
| runtime | 1 | 0 | 0 |
| scope | 1 | 0 | 0 |

## System surfaces

### artifact

- Package: noetrium_platform.evidence.artifact
- Authority: artifact_identity
- Canonical authority: artifact
- Node kind: authority
- Owns: immutable content identity, references, retention and catalog
- Must not own: mutable business state
- Requires: platform, scope
- Provides: artifact.registry
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.artifact

### data

- Package: noetrium_platform.evidence.data
- Authority: data_authority
- Canonical authority: data
- Node kind: authority
- Owns: durable facts, records, datasets, canonical state and projections
- Must not own: immutable artifact content identity
- Requires: artifact, platform, scope
- Provides: dataset.registry, projection.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.data

### data/fact

- Package: noetrium_platform.evidence.data.fact
- Authority: fact_authority
- Canonical authority: data/fact
- Node kind: authority
- Owns: durable fact envelopes and authoritative fact writes
- Must not own: business-specific state transitions
- Requires: none
- Provides: durable.fact
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.data__fact

### data/state

- Package: noetrium_platform.evidence.data.state
- Authority: state_authority
- Canonical authority: data/state
- Node kind: authority
- Owns: canonical mutable state and state-store contracts
- Must not own: disposable projections
- Requires: platform
- Provides: state.atomic
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.data__state

### environment

- Package: noetrium_platform.capabilities.environment
- Authority: environment_state
- Canonical authority: environment
- Node kind: authority
- Owns: environment specs, bindings, resolution and instances
- Must not own: project semantics and model serving
- Requires: governance/system_registry, platform, reliability, resource, runtime, scope
- Provides: environment.catalog, environment.category, environment.contract, environment.embodied.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment

### environment/gui

- Package: noetrium_platform.capabilities.environment.gui
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: desktop and mobile GUI environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, tool capability policy or OS process supervision
- Requires: environment, runtime
- Provides: environment.gui.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__gui

### environment/minecraft

- Package: noetrium_platform.capabilities.environment.minecraft
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: Minecraft environment contracts, server-control/world-cut semantics, state projection, bridge providers and readiness adapters
- Must not own: generic environment catalog, process/server supervision, model serving, project method semantics or telemetry storage
- Requires: artifact, environment, reliability, resource, runtime
- Provides: environment.minecraft.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__minecraft

### environment/software

- Package: noetrium_platform.capabilities.environment.software
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: repository and software-workspace environment contracts and provider adapters
- Must not own: benchmark scoring, repository policy, model serving or generic process supervision
- Requires: environment, resource, runtime
- Provides: environment.software.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__software

### environment/text_world

- Package: noetrium_platform.capabilities.environment.text_world
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: text-mediated stateful world contracts and provider adapters
- Must not own: dialogue method, benchmark scoring, agent memory or multi-agent topology
- Requires: environment
- Provides: environment.text_world.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__text_world

### environment/web

- Package: noetrium_platform.capabilities.environment.web
- Authority: none
- Canonical authority: environment
- Node kind: provider
- Owns: stateful web and browser environment contracts and provider adapters
- Must not own: benchmark cases, task scoring, browser automation policy or model serving
- Requires: environment, runtime
- Provides: environment.web.contract
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.environment__web

### execution

- Package: noetrium_platform.research.execution
- Authority: execution_operations
- Canonical authority: execution
- Node kind: authority
- Owns: workflow, canonical research-graph scheduling lifecycle, node attempt/lease state and operation orchestration contracts
- Must not own: provider storage, scientific result truth, effect truth, evidence truth or lower domain state
- Requires: artifact, environment, governance, model, observability, participant, platform, reliability, runtime, scope
- Provides: capability.invocation, capability.registration, method.abi, method.checkpoint, method.machine, research.machine.authoring, research.program, runtime.program, workflow.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.execution

### execution/operation

- Package: noetrium_platform.research.execution.operation
- Authority: operation_state
- Canonical authority: execution/operation
- Node kind: authority
- Owns: immutable execution command intent plus operation identity, lifecycle and result envelopes
- Must not own: failure taxonomy, recovery authority, provider effects or workflow orchestration
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.execution__operation

### experimentation

- Package: noetrium_platform.research.experimentation
- Authority: experimentation_state
- Canonical authority: experimentation
- Node kind: authority
- Owns: study, experiment, run, branch and checkpoint semantics
- Must not own: server/process control and model serving
- Requires: artifact, environment, execution, governance, model, participant, platform, portfolio, resource, scope
- Provides: experiment.catalog, experiment.definition, experiment.runtime, experiment.workload, research.workbench, run.checkpoint, run.control, run.decision, run.identity, run.lifecycle, run.manifest, study.definition
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.experimentation

### governance

- Package: noetrium_platform.foundation.governance
- Authority: none
- Canonical authority: none
- Node kind: facet
- Owns: architecture, quality, release and system topology rules
- Must not own: domain execution
- Requires: governance/system_registry, platform, scope
- Provides: architecture.audit, governance.evolution, quality.audit
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance

### governance/release

- Package: noetrium_platform.foundation.governance.release
- Authority: release_authority
- Canonical authority: governance/release
- Node kind: authority
- Owns: release identities, manifests, verification and promotion semantics
- Must not own: runtime process state
- Requires: none
- Provides: release.freeze
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__release

### governance/system_registry

- Package: noetrium_platform.foundation.governance.system_registry
- Authority: system_topology
- Canonical authority: governance/system_registry
- Node kind: authority
- Owns: recursive system topology and ownership declarations
- Must not own: runtime orchestration
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.governance__system_registry

### model

- Package: noetrium_platform.capabilities.model
- Authority: model_identity
- Canonical authority: model
- Node kind: authority
- Owns: model assets, stacks, assignments, deployments and serving identity
- Must not own: process lifecycle implementation and experiment semantics
- Requires: artifact, environment, platform, resource, runtime, scope
- Provides: model.asset, model.asset-acquisition, model.assignment, model.deployment, model.deployment-control, model.qualification, model.request, model.serving
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.model

### observability

- Package: noetrium_platform.evidence.observability
- Authority: none
- Canonical authority: none
- Node kind: projection
- Owns: logs, telemetry, traces, status and observation projections
- Must not own: durable state/failure authority
- Requires: governance, platform
- Provides: logging.observation, logging.routing, status.read-model, telemetry.metrics
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability

### observability/logging/storage

- Package: noetrium_platform.evidence.observability.logging.storage
- Authority: none
- Canonical authority: none
- Node kind: provider
- Owns: durable or volatile log storage backends
- Must not own: log schema policy
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.observability__logging__storage

### operator

- Package: noetrium_platform.product.operator
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: human-facing CLI, maintenance, incident and operator routing over the Research OS product surface
- Must not own: research authoring semantics, scientific graph authority, domain authority or business state
- Requires: governance, platform, research_os, runtime, scope
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.operator

### participant

- Package: noetrium_platform.capabilities.participant
- Authority: participant_state
- Canonical authority: participant
- Node kind: authority
- Owns: participant definitions, bindings, sessions, capabilities, agent specializations and participant-facing contracts
- Must not own: server/process supervision and scientific truth
- Requires: artifact, data, governance, platform, reliability
- Provides: agent.contract, capability.contract, method.contract, method.runtime, participant.definition, participant.runtime.abi, participant.session
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.participant

### platform

- Package: noetrium_platform.foundation.kernel
- Authority: platform_identity
- Canonical authority: platform
- Node kind: authority
- Owns: platform lifecycle, global identity, composition boundaries
- Must not own: domain business state and child internals
- Requires: none
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.platform

### portfolio

- Package: noetrium_platform.foundation.portfolio
- Authority: portfolio_metadata
- Canonical authority: portfolio
- Node kind: authority
- Owns: workspace/program/project metadata, immutable portfolio revision DAGs, branches, tags and portfolio organization
- Must not own: scientific payload bytes, study/run execution state, provider effects or evidence truth
- Requires: platform, scope
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.portfolio

### reliability

- Package: noetrium_platform.infrastructure.reliability
- Authority: none
- Canonical authority: none
- Node kind: facet
- Owns: effects, failures, incidents, forensics, diagnosis, reconciliation and recovery
- Must not own: scientific truth and UI projections
- Requires: data, governance, observability, platform, resource, scope
- Provides: diagnostics.causal, forensics.ledger, recovery.execution, recovery.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability

### reliability/effect

- Package: noetrium_platform.infrastructure.reliability.effect
- Authority: effect_authority
- Canonical authority: reliability/effect
- Node kind: authority
- Owns: external effect intent, outcome certainty and reconciliation state
- Must not own: process/server ownership
- Requires: none
- Provides: effect.journal, effect.safety
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__effect

### reliability/failure

- Package: noetrium_platform.infrastructure.reliability.failure
- Authority: failure_authority
- Canonical authority: reliability/failure
- Node kind: authority
- Owns: failure taxonomy, envelopes, fingerprints and semantic versions
- Must not own: diagnostic UI and operator policy
- Requires: none
- Provides: failure.truth
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.reliability__failure

### research_os

- Package: noetrium_platform.product
- Authority: none
- Canonical authority: none
- Node kind: product_surface
- Owns: single downstream research authoring, revision, graph-control and live-intervention product surface
- Must not own: domain authority, scientific execution truth, provider state or duplicated evidence
- Requires: artifact, data, environment, execution, experimentation, governance, model, observability, participant, platform, portfolio, reliability, resource, runtime, scope
- Provides: research.os
- Downstream surface: public
- Facade: noetrium.contracts.systems.research_os

#### API modules

- noetrium_platform.product.api ?w^~)?t ResearchPortfolioBuilder, ResearchPortfolio

### resource

- Package: noetrium_platform.infrastructure.resources
- Authority: resource_inventory
- Canonical authority: resource
- Node kind: authority
- Owns: resource inventory, compute, directories, leases and allocation/resolution
- Must not own: environment semantics and model deployment truth
- Requires: platform, resource/lease, scope
- Provides: compute.inventory, compute.scheduler, directory.layout, resource.endpoint-allocation, resource.hierarchical-resolution, workspace.storage
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.resource

### resource/lease

- Package: noetrium_platform.infrastructure.resources.lease
- Authority: resource_lease
- Canonical authority: resource/lease
- Node kind: authority
- Owns: lease identity, acquisition, renewal and release
- Must not own: server lifecycle
- Requires: scope
- Provides: resource.lease
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.resource__lease

### runtime

- Package: noetrium_platform.infrastructure.lifecycle
- Authority: runtime_state
- Canonical authority: runtime
- Node kind: authority
- Owns: server, process, service and session orchestration
- Must not own: experiment semantics and model catalog truth
- Requires: artifact, governance, governance/release, platform, resource, scope
- Provides: host.runtime, persistent-session.runtime, process.capture, process.execution, python-environment.execution, python-environment.lifecycle, python-environment.packages, python-environment.registry, runtime.toolchain, server.bootstrap, service.runtime
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.runtime

### scope

- Package: noetrium_platform.foundation.scope
- Authority: scope_tree
- Canonical authority: scope
- Node kind: authority
- Owns: generic hierarchical scope identity, ancestry and ownership paths
- Must not own: business metadata and runtime state
- Requires: platform
- Provides: none
- Downstream surface: metadata_only
- Facade: noetrium.contracts.systems.scope

