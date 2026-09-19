# Round 35 — Forensic Hash-Chain Core

- Extracted shared row hashing/encoding, file identity and immutable writer-tail state into `hashchain_core`.
- Both single-file and segmented forensic ledgers now replace one in-memory state object rather than mutating many independent fields.
- Kept O(1) steady-state append, verified-tail ownership, fail-closed competing-writer detection and global hash continuity across segment rotation.
- Raised append buffers to 1 MiB while retaining explicit flush/fsync policy; no evidence is silently discarded.
- This change is operational/performance-only and does not modify scientific dataflow.
