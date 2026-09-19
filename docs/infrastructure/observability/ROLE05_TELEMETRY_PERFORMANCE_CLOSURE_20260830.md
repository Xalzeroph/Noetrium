# ROLE05 Telemetry Performance Closure — 2026-08-30

`SQLiteTelemetryReader.summarize()` previously issued one indexed SQLite query for every percentile position required by p50/p95/p99. Although the position set is bounded, the implementation still amplified database roundtrips.

The reader now executes one window query using `ROW_NUMBER() OVER (ORDER BY value)` inside the same read transaction and returns all required percentile positions in one result set. Python memory remains bounded to the six p50/p95/p99 interpolation positions. Aggregate corruption checks, count/min/max/sum, percentile interpolation, and read-snapshot semantics are unchanged.

`tests/test_telemetry_query_summary_v207.py` verifies percentile compatibility and traces SQLite statements to prove exactly one window query is used and no per-position `OFFSET` query remains.

This is a real database-roundtrip reduction; no Performance Gate suppression or baseline edit is used.
