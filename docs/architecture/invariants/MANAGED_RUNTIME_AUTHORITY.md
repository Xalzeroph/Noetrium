# Managed runtime authority

`ManagedResearchRuntime` is a composition owner, not a new scientific authority. It may bind lifecycle, resource-admission, reconciliation, and shutdown authorities, but it must not redefine scheduling, model, method, experiment, trial, evidence, or journal semantics.

## Invariants

- Scientific identity is compiled before runtime orchestration.
- Runtime lifecycle state never becomes a second Machine Journal.
- Resource and model controllers consume canonical authorities through typed ports.
- Downstream Programs do not manage controller threads, pools, or shutdown ordering.
- New runtime automation belongs here only when it removes repeated infrastructure glue without introducing paper-specific semantics.
