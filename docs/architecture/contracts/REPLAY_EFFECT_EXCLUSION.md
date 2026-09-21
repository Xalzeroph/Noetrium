# Replay Effect Exclusion

Exact replay consumes recorded authoritative effects and must not invoke live providers for missing data. Observational or partial replay must declare its weaker level explicitly. A live fallback changes execution semantics and cannot be labeled exact replay.
