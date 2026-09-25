# Round 36 — Hot-Path I/O Optimization

- `SegmentedByteCapture` now keeps one immutable writer-state object and caches active segment size, avoiding `stat()` on every chunk.
- Capture hashing/reads are streaming (1 MiB buffers) rather than whole-file reads for verification and range access.
- Final partial capture bytes are fsynced before sealed manifest publication.
- Telemetry persistence is split into domain facade, SQLite backend and batch recorder.
- `TelemetryBatchRecorder` reuses one explicit SQLite writer session across batches instead of reconnecting per batch.
- Sequence allocation uses SQLite `last_insert_rowid()` after the transaction instead of querying global MAX(sequence).
- Online metrics still fail closed on invalid dimensions/values; no sampling or silent dropping was introduced.
