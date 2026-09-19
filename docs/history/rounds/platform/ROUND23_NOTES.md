# Round 23 — Forensic Index Self-Healing

- Kernel-backed single forensic writer lease.
- Derived index cut is proven by ledger row-count + tail-hash freshness records.
- Stale index is detectable even when the missing row resulted from a crash between authoritative append and SQLite indexing.
- Explicit exclusive atomic index rebuild from verified ledgers.
- Added `index-status` / `rebuild-index` operator commands.
