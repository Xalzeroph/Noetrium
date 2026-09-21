# Frozen Bindings Contract

Provider, model, environment and capability resolution may remain late until compilation, but MUST become immutable before execution. Every frozen binding carries stable identity and provenance and is journal-addressable. Runtime mutation requires a new run/child identity rather than in-place authority drift.
