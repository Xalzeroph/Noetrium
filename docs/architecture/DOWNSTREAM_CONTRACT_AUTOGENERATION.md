# Downstream contract surface and automatic exposure

## Purpose

Noetrium contains reusable systems whose contracts are implemented under `noetrium_platform`. Downstream projects must not depend on private providers merely because a system's public API was omitted from a hand-maintained facade.

The downstream surface is therefore generated from canonical source metadata:

1. `noetrium_platform/foundation/governance/system_registry/catalog.json` declares every registered topology node, ownership boundary, dependency, capability offer, `node_kind`, and `canonical_authority` relation.
2. Each registered package's public `api` surface declares the typed contracts and ports that the boundary makes available.

The generated artifacts include `noetrium/contracts/downstream_capability_catalog.json`, `docs/architecture/DOWNSTREAM_CAPABILITY_CATALOG.md`, the typed facades under `noetrium/contracts/systems/`, and the checked topology mirror `docs/architecture/VNEXT_SYSTEM_CATALOG.json`.

The topology mirror is not a second authority-classification source. Current authority interpretation follows `CURRENT_ARCHITECTURE_AUTHORITY.md` and `NOETRIUM_AUTHORITY_CONSOLIDATION_EXECUTION_SPEC_20260916.md`.

## What is generated

The generator records, for every registered topology node:

- system identity and parent-derived key;
- owning package;
- `node_kind` and canonical authority relation;
- direct authority identity only when the node is itself an authority;
- ownership and non-ownership semantics;
- required systems and provided capability keys;
- downstream surface mode;
- every discovered public API module eligible for the generated surface;
- every exported typed name;
- the stable generated facade import path;
- integrity digests used to reject stale or partially regenerated contract artifacts.

A registered node is not promoted to an authority merely because it receives a generated metadata facade. Facets, projections, providers, adapters, policies, tools, and product surfaces may remain discoverable without gaining a durable write path.

Every registered node receives generated metadata. A node without downstream API exports may be represented as metadata-only; it is not silently treated as an executable public API.

For example, a downstream consumer may import a generated facade such as:

```python
from noetrium.contracts.systems.runtime__session import (
    PersistentSessionSpec,
    PersistentSessionRuntimePort,
    RuntimeControllerCommand,
)
```

This exposes the contract surface needed by downstream composition while keeping concrete providers, credentials, sockets, process state, and private runtime implementation behind the platform boundary.

## Maintenance workflow

Run:

```bash
python scripts/generate_downstream_contracts.py
python scripts/generate_downstream_contracts.py --check
```

The first command regenerates the catalog, schemas, typed facades, and owned generated documentation. The second command is the drift invariant. It fails when registered topology metadata, API exports, node kinds, canonical-authority relations, or public symbols change without regenerating the downstream surface.

Adding a new topology node requires the canonical registry entry to declare its semantic kind explicitly. Adding a new public contract requires exporting it from the owning `api` package. The generated downstream surface then includes it without a second manually maintained list.

Adding a package or provider does **not** justify a new authority. New authority nodes must first pass the authority qualification test in the 2026-09-16 consolidation specification.

## Runtime boundary

`noetrium.contracts.discovery` is a read-only catalog/discovery API. Its explicit facade import operation is not a provider registry and is not a runtime service locator.

Runtime code still receives typed ports through composition roots:

```text
registry + api exports
        -> generated catalog/facades
        -> downstream composition root
        -> injected typed ports
        -> runtime/provider implementation
        -> owning authority acceptance path
```

The generated layer does not expose provider credentials, arbitrary concrete storage, ambient global state, or a universal `resolve(name)` runtime call.

## Authority boundary

Generated metadata must preserve the distinction between:

- topology ownership;
- direct authority ownership;
- canonical authority of a facet/projection/provider;
- downstream public exposure;
- concrete provider implementation.

`authority` is present as direct authority metadata only for nodes whose `node_kind` is `authority`. Non-authority nodes point at their canonical authority where applicable and must not manufacture a direct authority identity.

A downstream caller discovering a capability does not acquire the right to mutate its owner. Permission, capability scope, effect safety, run binding, and scientific validity remain separate contracts.

## Completeness invariant

The generated catalog must have the same registered key set and semantic metadata as the canonical system registry for the exact source cut. Every API symbol included in a generated facade must be importable from its owning public API module. Duplicate API modules or symbols, stale topology, node-kind drift, canonical-authority drift, schema drift, and digest mismatches fail closed.

Generated maps and catalogs must identify or otherwise be bound to the source revision from which they were produced. They are stale after relevant source changes and must be regenerated before release evidence is claimed.

The generated surface is a discoverability and contract boundary. It does not change authority ownership or bypass Machine execution, run control, resource admission, reconciliation, effect safety, evidence, or scientific-state rules.
