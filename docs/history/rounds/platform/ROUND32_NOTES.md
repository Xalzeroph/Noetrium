# Round 32 — Incident OS

- Added stable failure fingerprinting from domain/code/stage/component/operation/cause/effect/recovery.
- Volatile long numeric IDs and long hex tokens are normalized before fingerprinting, so repeated bugs cluster instead of fragmenting by request ID.
- Added a disposable SQLite recurrence index with first/last seen, count and bounded example failure IDs.
- Added `IncidentService` that combines recurrence identity with the existing DebugSnapshot: diagnosis, causal graph, timeline, recent state writers and nearby metrics.
- Incident OS does not invent causality from temporal proximity; it reuses authoritative forensic edges and marks recurrence only by a deterministic signature.
