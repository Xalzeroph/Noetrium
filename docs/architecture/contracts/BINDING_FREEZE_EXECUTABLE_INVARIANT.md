# Binding Freeze Executable Invariant

Resolution may be late, but execution bindings are immutable once canonical run identity is minted. Provider, model-role, environment, capability, benchmark, and participant bindings must be serialized into the frozen run manifest and journal-linked. Runtime mutation requires a new run identity rather than in-place rebinding.