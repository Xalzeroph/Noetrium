# Managed runtime health projection

Runtime health is an infrastructure projection.

- Health aggregates controller/task failures without redefining scientific outcome.
- `assert_healthy()` must surface latent supervised failures.
- Health probes cannot mutate run state.
- Dashboard health is derived from canonical runtime state, never a second authority.
