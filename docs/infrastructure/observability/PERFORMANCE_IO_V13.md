# I/O Performance Hardening — Round 13

## Forensic hash chain

The original reference implementation recomputed the complete hash chain before every append. That is excellent for a tiny prototype and pathological for a long Study: total append cost grows approximately quadratically with row count.

The writer now:

1. performs one full verification when the writer lifetime first touches the ledger;
2. caches `(row_count, tail_hash, file dev/inode/size/mtime)`;
3. computes the next hash in O(1);
4. refuses an unexpected external file mutation/competing writer;
5. retains explicit full `verify()` for operator/recovery checks.

Durability policy is intentional:

- failure ledger: fsync every row;
- authoritative mutation ledger: fsync every row;
- high-volume diagnostic event ledger: flush every row, group fsync every 32 rows.

This does not weaken hash verification. It separates steady-state append cost from independent full verification.

## Metric batching

`TelemetryBatchRecorder` validates each metric immediately but writes a batch in one SQLite transaction. The in-memory batch is removed only after commit succeeds, so a SQLite exception cannot silently drop the buffered observations. Execution IDs remain exact indexed columns.
