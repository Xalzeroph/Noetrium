# Round 38 — Compound Forensic Read Sessions

- Added explicit `ForensicIndexReadSession` for compound diagnosis operations.
- `DebugSnapshotService` now performs locate, timeline, recent-writer, diagnosis and causal-graph joins through one SQLite read connection.
- Existing one-shot index APIs remain thin wrappers around short read sessions.
- The session is deterministic and context-managed; no leaked query connection is allowed.
- This directly reduces incident-query connection churn without weakening read-only isolation or authoritative evidence rules.
