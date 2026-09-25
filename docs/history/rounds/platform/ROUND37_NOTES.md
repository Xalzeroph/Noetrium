# Round 37 — Forensic Projection Transactions

- Failure/event/mutation authoritative ledgers now use independent locks rather than one global store lock.
- The SQLite projection writer reuses one explicit writer connection.
- Hot append projection is one transaction: object index + optional state-writer + ledger freshness.
- Projection failure is now explicit as `ForensicProjectionError`: authoritative evidence remains committed and the disposable index is observably stale/rebuildable.
- Read-only forensic stores never create a writer connection.
- Store close now deterministically closes the projection writer before releasing the forensic writer lease.
