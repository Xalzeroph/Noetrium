# Noetrium directory architecture

This document defines the physical package layout for the reusable Noetrium
platform and its downstream-facing extension layers. A directory is created
only when it has one semantic owner and a real public contract.

## Naming

The implementation package is named noetrium_platform. A package named
platform would collide with Python's standard-library platform module.
noetrium is the minimal distribution metadata facade; public contract families
are imported explicitly from noetrium.contracts and native reference components.

## Semantic planes

    noetrium_platform/
      foundation/       kernel, governance, scope, portfolio
      infrastructure/   lifecycle, resources, reliability
      capabilities/     model, participant, environment
      research/         execution and experimentation
      evidence/         data, artifact, observability
      product/          operator and user-facing control contracts

The planes are grouping boundaries, not global registries. Each subsystem keeps
its own api, runtime, providers, and composition surfaces only when those
surfaces are semantically real.

## Root extension layers

    components/
      reference/single_agent/  reusable single-agent methods, memory, tools
    orchestration/
      multi_agent/             topology, communication and coordination
    noetrium/
      contracts/               stable public contract facades
      platform.py              thin platform composition facade

## Ownership and dependency direction

The dependency direction is strictly one way:

    downstream method -> components / orchestration
                       -> noetrium.contracts
                       -> explicit injected noetrium_platform implementation

The platform owns authority, identity, canonicalization, state, effects,
artifacts, execution context, recovery, and evidence. Components own reusable
single-agent mechanisms. Orchestration owns multi-agent topology and message
coordination. noetrium exposes stable contract entry points but does not
become a second runtime or authority registry.

Single-agent components execute one method. Multi-agent orchestration is a
higher layer: it coordinates agent nodes, messages, groups, debates, hierarchy,
and transport, but does not own cognition, memory, model providers, or truth.

## Extension rules

- Paper novelty stays in downstream repositories unless a mechanism is generic
  and independently reusable.
- Platform contracts are imported through public APIs and typed ports.
- Native providers are explicitly composed and injected; no ambient service
  locator or mega-registry is introduced.
- External project architectures are research inputs only. Platform code must
  not preserve their project names, object models, package shapes, adapters,
  compatibility facades, checkpoint formats, or runtime authorities.
- Mature external designs are rewritten as native Noetrium contracts and
  mechanisms before implementation; only downstream reproductions may retain
  source-project identity when scientific fidelity requires it.
- One durable truth has one semantic authority and one writer.
- Root extension layers must not import application-specific project code.
- New directories require a semantic owner and a real contract; empty symmetry
  packages are not created.
- Old package paths are not supported; migrations update consumers directly.
- Role numbers describe review and governance responsibility, not import order
  or directory nesting.
