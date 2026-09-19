# Single-mainline workflow

Noetrium uses one canonical development line: `main`.

Long-lived role branches, duplicated `master`/`main` tips, and parallel canonical worktrees are not part of the current workflow.

## Canonical state

- The public and canonical branch is `main`.
- Architecture, implementation, tests, generated contracts, and owning documentation converge on that branch.
- SEM and other research projects remain separate downstream repositories and are never edited as project-owned source inside this repository.
- Generated experiment state, runtime state, caches, and downstream project outputs remain outside the platform source tree unless they are explicitly versioned platform fixtures/evidence.

## Change protocol

1. Start from the current validated `main` tip.
2. Keep each commit focused on one semantic change and include the applicable tests, generated artifacts, and owning documentation.
3. Respect the architecture authority order in `docs/architecture/CURRENT_ARCHITECTURE_AUTHORITY.md`.
4. Run the applicable architecture, contract, repository-boundary, regression, and generation checks before treating the change as validated.
5. Update `main`; do not recreate permanent role branches or a second canonical branch.
6. If generated artifacts name a source Git SHA, regenerate them after architecture-changing source updates rather than carrying a stale snapshot forward.

## Concurrent work

Concurrency is allowed at the task/review level, but repository truth still converges through one mainline.

Independent agents or developers may research, review, or prepare isolated changes concurrently. Before integration, each change must be reconciled against the current `main` authority topology and tests. Two changes that create competing owners for the same truth domain must not be merged merely because they touch different files.

## Review and recovery

A reviewer may reject a commit with exact evidence. Recovery moves the mainline forward with a corrective commit or an explicit revert when appropriate; published history is not rewritten merely to hide a failed design or experiment.

Historical branches or commits may remain reachable as Git history, but they are not alternative current architecture authorities.

## Downstream synchronization

Downstream research repositories consume a pinned or otherwise explicit Noetrium source revision through the public contract surface. Platform changes discovered during downstream work should return upstream only when they are generic and do not import or encode the downstream project's scientific semantics.

A downstream project's frozen provenance must record the exact Noetrium revision it consumed. `main` advancing later does not retroactively change an already recorded experiment binding.