# Replay Authority

Replay consumes recorded authoritative inputs/effects according to its declared replay level. It must never invoke an unrecorded live effect and still claim exact replay. Any live fallback is an explicit new execution attempt with provenance linking it to the source run.
