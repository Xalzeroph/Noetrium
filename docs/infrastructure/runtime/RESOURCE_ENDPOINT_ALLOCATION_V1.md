# Resource endpoint allocation v1

## Ownership

`resource/lease` is the sole authority for resource identity, ownership, lease generation and fencing. `resource/allocation` owns endpoint reservation policy and the durable allocation record. `runtime/server` or an environment/server provider owns the live process/listener fact; Resource never infers real OS ownership from a database row.

The durable SQLite provider commits resource ownership, the lease, and the endpoint allocation in one transaction. In-memory allocation remains an explicitly process-local authority for deterministic composition/tests and is not restart-safe.

## Endpoint state machine

An allocation has exactly three states:

```text
RESERVED -> BOUND -> RELEASED
```

`RESERVED` means the logical endpoint resource is exclusively leased and persisted. It does **not** mean that a process is listening. `BOUND` requires an `EndpointBindingProof` produced by the runtime/environment authority that can actually verify the listener. `RELEASED` is terminal for that allocation identity.

`EndpointBindingProof` binds the allocation id, exact endpoint, current lease fencing token, a SHA-256 binder identity digest, observation time, and an evidence reference. Resource accepts the proof only while the allocation is live and the fencing token still matches the authoritative lease. A repeated identical proof is idempotent; a conflicting proof or stale fencing token fails closed.

Release clears the live lease but preserves historical binding evidence on the released allocation so lifecycle evidence is not erased by cleanup.
## Allocation and recovery semantics

`EndpointAllocationRequest` contains the explicit host, protocol, ordered candidate ports, holder scope, owner scope and purpose. Candidate selection first checks the injected OS availability probe, then asks the atomic reservation authority to commit ownership + lease + allocation. Concurrent contenders are serialized by the durable transaction and fencing token rather than by probe timing.

SQLite schema v3 adds binding proof metadata. Historical v2 rows whose allocation state was `active` are migrated fail-closed to `reserved`, because the old schema did not contain proof that a listener existed. Reopen reconciliation expires stale leases and changes orphaned `RESERVED` or `BOUND` allocations to `RELEASED` without inventing a new listener fact.

Renewal is fencing-aware. Batch renewal is one transaction: if any allocation is missing, released, or loses fencing, the batch rolls back rather than partially extending a set of endpoints. The heartbeat guard surfaces renewal failure to its owner and does not silently degrade to an unleased endpoint.

## Consumer boundary

Consumers may use a `RESERVED` endpoint to configure a server launch, but they must not interpret reservation as readiness. After the concrete runtime has started the server and authoritatively verified endpoint ownership, that owning runtime/environment layer should submit `EndpointBindingProof` through `EndpointAllocationPort.confirm_bound()`.

Minecraft and platform composition currently consume the endpoint port but do not own Resource persistence. Their cutover to listener-attested `BOUND` is a cross-system consumer migration and must be reviewed by the corresponding owners; Resource does not reach into those production paths.

## Test placement

- L1 / WINDOWS: state, proof, digest and fencing contracts.
- L2 / WINDOWS: deterministic in-memory allocator behavior.
- L4 / BOTH: SQLite schema migration, reopen, expiry, reconciliation and transactional renewal.
- L5 / BOTH: concurrent reservation/lease races and multiprocess contention.

A local PASS never proves a live listener. Live endpoint ownership is evidence supplied by the runtime/environment authority on the exact tested source identity.
