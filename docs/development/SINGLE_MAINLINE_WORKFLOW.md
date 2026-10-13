# Development Workflow

Noetrium develops against one canonical branch: `main`.

## Principles

- Keep a change scoped to one semantic purpose.
- Identify the subsystem that owns the affected durable fact or effect before editing code.
- Do not create a second scheduler, journal, resource ledger, checkpoint authority, or provider fallback to solve a local inconvenience.
- Keep project-specific scientific logic outside the reusable platform.
- Treat performance changes as semantic changes when they alter ordering, lifetime, admission, effects, or evidence.
- Keep local paths, credentials, experiment outputs, machine inventories, caches, and one-off probes out of commits.

## Change protocol

1. Start from the current `main` tip.
2. Add or update the smallest implementation that owns the behavior.
3. Add focused tests for success, failure, recovery, and uncertainty where relevant.
4. Run the applicable architecture/public-contract/governance gates.
5. Update maintained documentation when the public or architectural contract changes.
6. Regenerate source-derived metadata only from the source cut it describes.
7. Integrate only after the code, tests, generated artifacts, and documentation agree.

Concurrent investigation is fine, but canonical repository truth converges through one mainline. Reviewers may inspect work in isolation; they do not need to create another persistent architecture authority.

## Downstream boundary

Research projects consume an explicit Noetrium version or revision through the public surface. A mechanism discovered downstream belongs upstream only if it is reusable without importing that project's private scientific semantics, assets, results, deployment inventory, or benchmark-specific policy.

## Release changes

Release preparation must use a clean source tree. Version metadata, README claims, package metadata, release evidence, wheel/sdist contents, and container provenance must all identify the same source cut. See [`../governance/RELEASE_SYSTEM.md`](../governance/RELEASE_SYSTEM.md).
