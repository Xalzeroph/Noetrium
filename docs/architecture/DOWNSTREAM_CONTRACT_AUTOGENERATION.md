# Downstream contract surface and automatic exposure

## Purpose

Noetrium contains reusable systems whose contracts are implemented under
`noetrium_platform`. Downstream projects must not depend on private providers
merely because a system's public API was omitted from a hand-maintained facade.
The downstream surface is therefore generated from two canonical sources:

1. `noetrium_platform/foundation/governance/system_registry/catalog.json`
   declares every registered system, ownership boundary, dependency and
   capability offer.
2. Each registered package's `api` surface declares the typed contracts and
   ports that the system makes available.

The generated artifacts are
`noetrium/contracts/downstream_capability_catalog.json`,
`docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md`, and the typed facades
under `noetrium/contracts/systems/`. The same generator refreshes
`docs/architecture/VNEXT_SYSTEM_CATALOG.json` from the canonical registry, so
topology documentation is not maintained as a separate manual copy.

## What is generated

The generator records, for every registered system:

- system identity and parent-derived key;
- owning package and authority;
- ownership and non-ownership semantics;
- required systems and provided capability keys;
- every discovered public API module;
- every exported typed name;
- the stable generated facade import path.

A system without an API export remains visible in the catalog with
`facade_module = null`. This is intentional: a topology node is not silently
treated as an executable public API.

For example, the generic persistent-session system is exposed through:

```python
from noetrium.contracts.systems.runtime__session import (
    PersistentSessionSpec,
    PersistentSessionRuntimePort,
    RuntimeControllerCommand,
)
```

This includes the contract surface needed by downstream runtime composition while
keeping tmux provider classes and SSH credentials behind the platform boundary.

## Maintenance workflow

Run:

```bash
python scripts/generate_downstream_contracts.py
python scripts/generate_downstream_contracts.py --check
```

The first command regenerates the catalog and typed facades. The second command
is the CI invariant. It fails when a registered system, API export, or public
symbol changes without regenerating the downstream surface.

Adding a new system requires only its canonical registry entry and its normal
`api` package. Adding a new contract requires exporting it from the owning
`api` package. The generated downstream surface then includes it without a
second manually maintained list.

## Runtime boundary

`noetrium.contracts.discovery` is a read-only catalog/discovery API. Its
explicit facade import operation is not a provider registry and is not a
runtime service locator. Runtime code still receives typed ports through
composition roots:

```text
registry + api exports
        -> generated catalog/facades
        -> downstream composition root
        -> injected typed ports
        -> runtime implementation
```

The generated layer does not expose provider implementations, credentials,
arbitrary concrete storage, or a universal `resolve(name)` runtime call.

## Completeness invariant

The catalog must have exactly the same system-key set as the canonical system
registry. Every API symbol included in a generated facade must be importable from
its owning API module. A generated surface is a discoverability and contract
boundary; it does not change authority ownership or bypass release,
reconciliation, effect-safety, or scientific-state rules.
