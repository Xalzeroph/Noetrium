# Replay Semantics

Replay consumes frozen identity plus recorded journal/effect evidence at an explicit replay level. Replay must never silently call live providers where evidence is required, nor claim stronger reproducibility than the selected level supports. Missing evidence is surfaced as a typed limitation.
