# Forensic Ledger Invariants

Authoritative forensic ledgers are append-only hash chains; SQLite projections are disposable accelerators.

- A projection synchronizes against a typed `VerifiedLedgerCut` that binds the source checkpoint row/hash to one verified total row count and tail hash.
- Production projection rebuilds do not materialize the entire verified suffix. After verifying the cut, they re-verify that fixed cut while yielding bounded payload batches.
- The second pass is bound to the previously verified row count, checkpoint hash, and tail hash. Appends after the cut are deferred to the next synchronization; prefix mutation or truncation between passes fails with `HashChainError`.
- Incident projection changes stay inside one SQLite transaction while the full fixed cut is streamed. A later integrity failure therefore rolls back earlier projected batches.
- The legacy materialized `VerifiedLedgerSlice` remains suitable for low-volume diagnostic reads and tests, but production rebuild paths use bounded streaming.
- Failure and mutation ledgers fsync every authoritative append. Event telemetry may batch fsync/projection according to its explicit durability policy; integrity verification still spans the global event hash chain.
- Projection freshness is never authoritative evidence of ledger truth. It is accepted only when its row/hash checkpoint matches the verified authoritative prefix.
- Linux directory-mutation authority uses one process-wide inotify instance with independent watch-token latches; one ledger must not consume one kernel inotify instance.
- Linux never silently degrades to directory `stat()` when inotify initialization or watch registration is unavailable. Registration failure is fail-closed because stat timestamps are not an equivalent mutation authority.
- A drained shared inotify event marks every live token attached to that watch descriptor, so one consumer cannot erase another consumer's pending mutation observation.
- Server2 conformance keeps more simultaneous watched ledgers than its `max_user_instances=128` limit would permit under one-fd-per-ledger design and requires every signal to remain in `inotify` mode.
- After `fork()`, the child abandons the inherited inotify fd and process-local token registry before opening a new hub; parent and child must never drain each other's mutation events.
- Multiple tokens for the same directory share the kernel watch descriptor but retain independent pending latches; acknowledging one consumer does not acknowledge another.
- Exhausted Linux inotify watch capacity is a typed operating-system failure boundary: construction fails closed and must be surfaced by preflight/doctor rather than silently changing to a weaker mutation detector.

## Typed forensic write actor

- `ForensicWriteActorPort` is a serialization/execution seam, not a generic payload authority.
- Its callable, positional arguments, keyword arguments, and return value remain related through `ParamSpec` + `TypeVar`; the public contract must not erase those relationships with `Any`.
- The actor may order an authority-owned call but does not redefine the ledger/index schema or bypass the called authority's validation and transaction semantics.
