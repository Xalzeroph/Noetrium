# Documentation Change Policy

Documentation is part of the governed change surface. A source, configuration, test, packaging, deployment, or governance change is incomplete until the owning documentation and required generated artifacts are updated in the same change set or deterministic regeneration closure.

## Required same-change updates

Update the smallest canonical document that owns the changed contract or verified state:

- architecture, authority classification, ownership, or execution-truth change -> `docs/architecture/`;
- reusable infrastructure change -> the matching `docs/infrastructure/<owner>/` document;
- governance or operational-policy change -> `docs/governance/`;
- source-cut platform development/verification state change -> `docs/status/`;
- important completed platform milestone -> an immutable note under `docs/history/rounds/platform/` when useful.

Downstream project methods, benchmark/environment implementations, model selections, deployment inventories, and scientific results are documented in the downstream repository, not copied into the upstream platform documentation tree.

A code comment, commit message, chat transcript, generated report, or status snapshot is not a substitute for the canonical owner document.

## Documentation authority rule

`docs/architecture/CURRENT_ARCHITECTURE_AUTHORITY.md` defines the current documentation precedence and supersession rules.

The canonical system registry owns live topology metadata. The current normative authority-classification/execution specification and machine-readable disposition matrix determine which registered boundaries are authorities versus facets, projections, providers, adapters, policies, tools, or product surfaces.

A generated topology mirror, source map, capability catalog, interface schema, architecture report, status baseline, or release artifact is evidence for the exact source cut it records. It must not silently override a newer normative contract or be cited as current evidence after relevant source changes.

## Current-state rule

`docs/status/CURRENT_DEVELOPMENT_BASELINE.md` records the latest maintained development baseline and known validation state for the reusable upstream tree. Update it when repository boundaries, package/release identity, validation state, or active platform migration gates materially change.

It is a source-cut status projection, not the highest architecture authority. Historical validation counts remain historical evidence and must not be copied forward as current results.

Generated algorithm, concurrency, performance, code-architecture, downstream-contract, and release reports belong in their owned locations. They are current only when regenerated and validated against the exact source/release identity being inspected.

## Supersession rule

When a newer design supersedes only part of an older document, preserve the older rationale but add an explicit notice near the title or route readers through `CURRENT_ARCHITECTURE_AUTHORITY.md`.

Do not silently rewrite history to imply that the current architecture always existed. Do not leave a historical document phrased as a current authority when a later normative specification has replaced that part of it.

## Upstream-source evidence rule

When an adapter/provider change depends on third-party protocol or library behavior, inspect the exact pinned upstream version before changing behavior. Record the relevant upstream contract in the owning provider documentation, implement the narrowest compatible change, and validate against the pinned dependency. Do not invent wire behavior, event ordering, tolerance rules, or lifecycle semantics when authoritative upstream source can answer the question.

External repositories and papers are research inputs, not automatic runtime dependencies or authority transfers. Absorb the reusable mechanism into the existing Noetrium authority/provider boundary instead of copying a foreign lifecycle wholesale.

## Commit discipline

Prefer one reviewable change set containing implementation, focused tests, generated governance evidence when required, and the owning documentation. If unrelated work is already dirty, stage only files owned by the current change and preserve unrelated worktree state.

Generated artifacts that bind a source Git SHA must be regenerated after architecture-changing source updates. A CI regeneration closure may commit deterministic generated artifacts after the source/document change, but the final mainline must converge to one consistent source cut.

Frozen release evidence is never rewritten merely to make documentation appear current. Generate new evidence for a new release/source identity.
