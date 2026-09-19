# Round 30 — Prompt Role Decomposition + Raw Telemetry Lake

## Changes
- Split monolithic `prompt_os.roles` into independently versionable role modules.
- Split the metric catalog into bounded metric-family modules; aggregator only composes families.
- Expanded the default low-cardinality metric catalog to 170+ metrics.
- Added append-only `RawObservationLake` for high-cardinality/debug-rich evidence.
- Raw records carry the complete `ExecutionContext` and arbitrary family payload; metrics keep only bounded labels.
- Added per-record SHA-256 integrity and explicit schema/retention family registry.
- No sampling, silent dropping, fallback model, prompt fallback, or quality degradation path was added.

## Observability principle
Record broadly first.  Use low-cardinality metrics for online aggregation and the raw lake for exact IDs, payloads, provider receipts, token/accounting details and forensic joins.  Filtering/rollup is downstream; authoritative raw capture remains intact.
