# Binding Freeze Invariant

Study requirements are resolved late, then frozen exactly once into run identity. Execution may consume frozen bindings but may not silently re-resolve providers, models, environments, or capabilities mid-run. Any intentional rebinding creates a new authoritative run identity.
