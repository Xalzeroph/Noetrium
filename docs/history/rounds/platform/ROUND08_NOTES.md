# Round 08 — Error Taxonomy / Redaction / Crash Bundles

- Central stable `FailureCatalog` and `FailureSpec`.
- Secret-safe exception chain persistence and failure fingerprints.
- `FailureRecorder` produces one failure + one terminal event at an owning boundary.
- Bounded pre-failure breadcrumb buffer for local context; authoritative evidence remains append-only.
- Immutable, digest-bound Crash Bundle manifest with timeline, state writers and ledger tail proofs.
- AST-level silent-failure audit for broad swallowed exceptions.
