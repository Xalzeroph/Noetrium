# Round 28 — One-Shot Debug Snapshot and Causal Projection Decomposition

## Debugging surface

`noetrium-forensics debug-snapshot <forensic-root> <object-id>` now returns one read-only joined snapshot containing:

- exact object payload;
- structured failure diagnosis when the object is a failure;
- explicit-reference causal graph;
- local timeline (correlation only, never promoted to causality);
- recent authoritative state writers;
- nearby raw telemetry when `--telemetry-db` is supplied.

This collapses the common manual debugging sequence into a single query without inventing new causal edges.

## Physical decomposition

- causal graph context projection and reference projection moved into dedicated projectors;
- graph builder is now orchestration only;
- operator dispatch is split by domain route rather than one growing central branch table.

No fallback, model substitution, quality downgrade, prompt truncation or method substitution was added.
