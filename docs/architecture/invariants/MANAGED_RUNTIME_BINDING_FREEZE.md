# Managed runtime binding freeze

Managed execution consumes compiled bindings; it does not resolve scientific dependencies anew.

- Provider/model/environment/capability resolution freezes before run execution.
- Runtime placement may select only within the frozen policy.
- Binding digest participates in canonical run identity.
- Mid-run semantic rebinding requires a new run identity.
