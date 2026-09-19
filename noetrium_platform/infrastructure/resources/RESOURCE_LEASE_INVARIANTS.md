# Resource Lease Invariants

ROLE 02 treats lease time as fencing state, not display metadata.

- Every lease TTL, expiry timestamp, renewal interval, bind observation time, and provider observation clock must be finite.
- `NaN` and positive/negative infinity are invalid at typed-contract and provider boundaries. A non-finite expiry can otherwise become an immortal stale lease because ordered expiry comparisons never succeed.
- Endpoint reservation is not listener ownership. Allocation remains `RESERVED` until a current-fencing `EndpointBindingProof` is confirmed by the allocation authority.
- Renewal preserves the current fencing token. Expiry/reallocation must advance fencing before the same resource can be owned by a new holder.
- SQLite and in-memory authorities enforce the same temporal contract; durable restoration is not allowed to weaken it.
- Heartbeat failure is fail-closed and must surface to the owning structured task rather than silently extending logical ownership.

The downstream Minecraft bind cutover remains a consumer responsibility tracked by the existing cross-system change request; Resource does not infer `BOUND` from its own reservation record.

BOUND is also generation-fenced, not a permanent one-time label. A process restart may replace the binding proof only through the typed BOUND→BOUND compare-and-swap operation.

- Replacement must retain the exact allocation id, endpoint, live lease and current fencing token.
- The caller supplies the exact previous binding-proof digest; stale or concurrent generations fail closed.
- The new binder identity must differ from the currently persisted binder identity.
- Binding proof digest, binder identity digest, readiness evidence reference, and producer-observed bind timestamp are one atomic metadata generation.
- In-memory and SQLite providers implement identical CAS semantics; SQLite persists the winning generation in one transaction and restart must recover exactly that winner.
- `confirm_bound` remains reserved for initial `RESERVED -> BOUND` plus exact current-proof idempotent replay; it never performs generation replacement.

## Shared durable SQLite connection hardening

Resource Lease and Endpoint Allocation are independent authorities but share durable SQLite session mechanics through `providers.sqlite_connection.durable_sqlite_connection` and canonical `ResourceOwner` / `ResourceLease` transitions through `providers.sqlite_lease_ops`.

- The connection primitive owns only connection/session hardening: finite positive timeout, SQLite busy timeout, bounded retry of `journal_mode=WAL` only for lock contention, `synchronous=FULL`, foreign-key enforcement, and guaranteed close.
- `sqlite_lease_ops` owns generic resource-owner registration plus lease acquire/renew/release/expiry/fencing persistence; it owns no endpoint-allocation, listener-binding, candidate-selection, or endpoint-reconciliation semantics.
- `SQLiteResourceLeaseRegistry` and `SQLiteEndpointAllocationStore` retain separate `BEGIN IMMEDIATE` writer transactions and independent authority state machines while consuming the same lease transition core.
- Non-lock SQLite errors remain fail-closed; the helper does not broaden transient classification into a generic fallback.
- Local Windows and Server2 Linux providers must exercise the same helper semantics; provider location cannot weaken durability or deadline behavior.
