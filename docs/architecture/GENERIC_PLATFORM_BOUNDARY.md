# Generic Platform Boundary

## Replaceable units

Scientific/project-specific implementations live behind stable contracts:

```text
projects/<project>/method/<project_method>/
environments/<environment>/
agent implementations
capability providers
service/process backends
storage/projection backends
```

Everything else should remain reusable infrastructure or a narrow API/runtime implementation.

## Runtime composition

```text
composition
├── StudyRuntimeComponents
├── ParticipantResolutionPort
├── ParticipantSessionLifecyclePort
├── ParticipantCheckpointOperationsPort
├── OperationDispatchPort
├── ExactServiceRuntimePort
├── model/prompt/release verification ports
├── model-request/scoped-registration/projection runtimes
└── workflow/capability/effect runtime bindings
```

`StudyRuntime` does not construct participant/workflow implementations. Concrete joining happens in `composition`.

## Implementation is not runtime

A method/agent/environment/capability implementation declares functional/scientific identity. Session runtime and endpoint identity are separate. A frozen participant binding joins implementation identity, runtime identity and configuration identity.

## Platform must not know

- project-specific method state types, operators, or evolution semantics;
- environment-specific entity, object, protocol, or transport semantics;
- method-specific acceptance metrics;
- concrete service/model/prompt storage layout from outside the owning system;
- concrete telemetry/forensic persistence backends from project/runtime code.

## Method must not know

- environment transport implementations;
- process/session supervision implementations;
- accelerator topology and placement implementations;
- model-serving backend process management;
- deployment credentials or release packaging;
- telemetry/forensics backend implementations.

## Environment must not know

- method architecture generation;
- treatment arm/candidate adoption state;
- prompt qualification internals;
- `J_mem/J_audit` semantics beyond generic evidence contracts.

## Capability policy must not know

- how effect WAL/persistence is implemented;
- how external-effect certainty is reconciled;
- how telemetry is persisted.

It can guard/approve/post-process, but it cannot bypass the effect-safe executor.

## Composition-root rule

Only composition roots may depend on unrelated concrete implementations to bind ports together. Domain/runtime packages depend on API/ports across system boundaries.

## Project ownership and injected system interfaces

A concrete research or application project is not a generic platform subsystem.
Its method state machine, domain semantics, task definitions, evidence
interpretation, serving policy, evaluation policy, and experiment composition
remain owned by the downstream project.

```text
noetrium_platform/<system>/api/       # stable platform contract
downstream-project/composition/       # project composition root
downstream-project/<domain>/          # project-owned implementation
```

The platform exposes contracts and ports. A downstream project implements or
binds project-owned behavior behind those contracts without becoming a second
platform authority. Runtime consumers still receive the narrowest injected
port; no global service locator is introduced for convenience.

The following are forbidden even when they would be convenient:

- a project depending on platform-private runtime/provider implementations when
  a public contract exists;
- the platform importing a concrete downstream project to satisfy a generic
  default;
- moving project-specific truth into a generic platform manager or registry;
- treating a project-local adapter as reusable platform authority without a
  separately designed and reviewed generic contract.

## Repository boundary

The long-term repository contract is intentionally asymmetric:

```text
upstream platform repository
        │
        ├── published/installed as a dependency, or
        └── forked as a stable platform baseline
                 │
                 ▼
       downstream project repository
```

The platform repository contains reusable infrastructure, contracts, governance,
release tooling, and generic provider boundaries. Project-specific methods,
benchmarks, environment compositions, model selections, deployment inventories,
and experiment results belong in downstream repositories.

Dependency direction is one-way: downstream projects may depend on the platform;
the platform must never depend on a downstream project. Any project code still
present in a platform development checkout is transitional extraction material,
not part of the reusable platform ownership boundary.
