# Round 142 — Study streaming-aggregation optimization rejected before freeze

Date: 2026-08-28

## Candidate optimization

A working-tree change replaced list-backed mean/sample-variance aggregation with Welford streaming moments. The candidate reduced per-group sample retention from O(N) to O(1) state and is numerically stable in the usual statistical sense.

## Rejection reason

The existing scientific protocol does not yet carry an explicit aggregation-algorithm identity. Direct comparison showed that Welford changes IEEE-754 results in the final bits relative to the existing `sum(values) / n` and two-pass sample-variance implementation.

Those aggregates are published as study evidence and may be consumed by downstream scientific closures. Changing their exact numerical projection without freezing a new aggregation algorithm identity would create an unversioned scientific-semantic change.

## Decision

The candidate patch was preserved under local `.server-state` forensic state and removed from the active worktree. The current Study implementation retains the pre-existing exact floating-point behavior.

A future streaming aggregator must first become an explicit, versioned protocol/scientific identity and must receive compatibility and evidence-migration tests before promotion.
