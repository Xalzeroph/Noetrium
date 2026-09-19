# Telemetry OS — Round 09

## Strategy: collect broadly without cardinality collapse

The platform intentionally records a broad metric surface. High-cardinality execution identities are not thrown away: they are persisted as indexed columns in `TelemetryStore` (`run_id`, `task_id`, `decision_cycle_id`, `trace_id`, `span_id`, `operation_id`, generations). They are **not metric dimensions**.

This gives both:

- low-cardinality metric series suitable for aggregation;
- exact per-request/task/cycle forensic joins.

The default registry now spans generic operations, LLM client attempts, Prompt OS, model serving, GPU/CPU/host, SQLite/journals, checkpoints/recovery, operator forensics, Study/resource scheduling, Method/Memory/Evolution, and Environment transport.

## Data-quality rules

- every metric must be registered;
- dimensions must be declared and bounded;
- NaN/Inf are rejected;
- counter increments cannot be negative;
- ratio metrics must remain in `[0,1]`;
- high-card IDs are forbidden as dimensions but retained in `ExecutionContext` columns.

No scientific or runtime behavior changes based on these metrics. They are observational evidence for later filtering, performance analysis and debugging.

## Raw-observation preflight

Raw scientific observations are canonical-JSON validated before a persistence actor or
segment writer is created. Invalid payloads such as NaN/Inf therefore fail before any
segment file or writer-lock side effect exists. Durable append, fsync, idempotency, and
sequence ownership begin only after this storage-neutral preflight succeeds.

## Summary query complexity

`SQLiteTelemetryReader.summarize()` performs corruption validation and aggregate lookup in a
single read transaction. P50/P95/P99 require exactly six bounded order-statistic positions.
Those six positions are projected by one SQLite window/conditional-aggregation query returning
one fixed-width row; Python performs no input-sized percentile loop or result comprehension.
This keeps provider-side control complexity `O(1)` and one percentile database roundtrip while
preserving linear interpolation semantics and the covering value index.
