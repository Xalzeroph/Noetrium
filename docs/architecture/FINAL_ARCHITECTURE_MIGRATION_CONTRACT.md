# Final Architecture Migration Contract

This contract defines how the reusable platform may change ownership boundaries without creating compatibility aliases, duplicate authorities, or hidden service lookup.

## Completion objective

A migration is complete only when the target owner is the unique authority, all runtime consumers depend on its public contract, durable state has one writer, old construction paths are deleted, and the architecture/test/release gates prove the new topology.

Migration is not complete merely because a replacement implementation exists.

## Target ownership model

```text
platform system
├── api/          stable public contracts and identities
├── runtime/      execution/lifecycle semantics owned by the system
├── providers/    replaceable adapters owned by the system
└── composition/  provider-to-port binding

external/downstream implementation
└── depends only on the public platform contracts it consumes
```

Concrete downstream methods, benchmark adapters, environment providers, model selections, and deployment composition remain downstream-owned implementations. They are not promoted into generic platform ownership solely because one project uses them.
## Three-plane rule

Every migration preserves three distinct planes:

1. **command/runtime plane** — typed calls on the owning runtime port;
2. **durable truth plane** — state written through the unique state authority;
3. **observation plane** — logs, events, metrics, traces, diagnostics, and projections.

Observation cannot become a hidden command bus. A projection cannot become a second durable writer. A convenience composition helper cannot become a service locator.

## Migration state machine

A subsystem migration follows:

```text
inventory → contract → provider → composition → dual verification → consumer cutover → deletion → release evidence
```

Dual verification means comparing old/new behavior only while the old path still exists; it does not authorize permanent dual authorities. Once the target path is proven and consumers are cut over, the old authority is deleted rather than kept as a compatibility fallback.
## Required evidence

Each migration slice records:

- source/target ownership and dependency direction;
- public contract changes and compatibility impact;
- state/data migration and recovery behavior when durable state is involved;
- focused regression tests plus affected higher-level gates;
- architecture/source-authority evidence;
- algorithm/concurrency/performance evidence when governed hot paths change;
- documentation updated in the same change set.

## Deletion gate

Delete the retired path only after no production consumer imports it, durable state has a verified migration/recovery path, tests cover the replacement authority, and generated release evidence is built from the new tree.

## Repository-boundary migrations

Moving a downstream project out of the reusable platform follows the same contract. Preserve the downstream source/history first, remove downstream packages from upstream packaging/runtime/release inventories, prove the upstream works without them, then establish the downstream repository as a one-way consumer of the platform.

See [`DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md`](DOWNSTREAM_PROJECT_REPOSITORY_CONTRACT.md) for the repository-level rule.

## Cross-role dependency declaration companion

When a downstream-owned adapter introduces a real import from one top-level system into another, the canonical registry must declare that dependency at the owning top-level boundary instead of hiding it behind dynamic imports or a second locator. The dependency declaration is a governance projection of the real typed contract; it does not transfer runtime or durable-state authority.

The run-control operator cutover is the concrete acceptance case: `operator` declares `execution` and `experimentation` because the ROLE06 operator adapter consumes the ROLE03 run-control contract. Those two declarations are charged to the ROLE01 governance migration, while the adapter import-edge delta remains charged to ROLE06.

Changing canonical catalog complexity invalidates any exact-SHA external architecture approval bound to the prior ROLE01 source. The worker updates only migration request facts; ROLE00 must independently reissue the matching full-complexity approval for the new exact source. Stale approvals contribute zero headroom.
