# Forensic Index v23 — Proven Cut / Atomic Rebuild

SQLite is explicitly **derived**. Authoritative evidence remains the failure/event/mutation hash chains.

Every successful append updates `ledger_freshness(ledger, rows, tail_hash)` after indexing. If the process dies after the authoritative append but before either index write or freshness update, the index becomes mechanically `STALE` rather than silently incomplete.

`noetrium-forensics index-status RUN_ROOT` compares the independently verified authoritative `(row_count, tail_hash)` triplet with the index cut.

`noetrium-forensics rebuild-index RUN_ROOT` is an explicit mutating maintenance action:

1. acquire the kernel single-writer forensic lease;
2. verify all authoritative chains;
3. build a brand-new SQLite index from the verified payload bytes;
4. record exact ledger freshness cuts;
5. verify the authoritative chains again to reject concurrent source changes;
6. atomically replace only `index.sqlite3`.

The three authoritative chains are never rewritten. Rebuild refuses to start while the runtime writer lease is held.
