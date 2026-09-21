# Managed runtime autoscaling

Autoscaling is infrastructure policy, not scientific method semantics.

- Replica count and worker count are excluded from treatment identity unless explicitly declared as an experimental variable.
- Scaling decisions cannot mutate frozen bindings.
- Scaling events remain runtime provenance.
- Capacity exhaustion is distinct from scientific failure and scheduler faults.
