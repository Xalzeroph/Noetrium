# Round 13 — O(1) Hash Append / Batched Telemetry

- Removed O(n)-per-event full chain scan from steady-state append.
- Added owner file identity/signature detection for competing mutation.
- Failure/mutation ledgers remain sync-on-append; event ledger uses explicit group fsync.
- Added transactional TelemetryBatchRecorder with clear-after-commit semantics.
