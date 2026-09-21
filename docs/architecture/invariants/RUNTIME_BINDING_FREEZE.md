# Runtime binding freeze

The managed runtime consumes compiled frozen bindings; it does not resolve scientific providers after execution starts. Operational replacement is permitted only within the equivalence class described by the frozen binding and must be recorded in effect metadata.

A change that alters semantic model, environment, capability, benchmark, participant, or treatment binding requires a new compiled run identity.
