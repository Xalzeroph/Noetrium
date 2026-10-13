# Universal Resource Authority Invariants

Resource lifecycle truth is singular. `UniversalResourceAuthority` is the only durable owner of resource generation, capacity, claims, leases, single-flight realization tickets, bindings, fencing, retirement state, and reconciliation progress. Placement and probes provide facts only; Providers perform physical effects only.

- Every TTL, expiry time, renewal interval, observation time, and provider clock is finite and positive when present. `NaN` and infinities are invalid.
- A resource generation is the universal fencing token. Any stale-generation claim, lease, ticket, observation, binding, or release fails closed.
- Capacity admission, exclusive-token collision checks, claim persistence, and lease-admission fencing are atomic Authority transitions.
- Unknown capacity dimensions fail closed. Old-generation claims continue consuming capacity until their physical realization is proven absent and the claim is released.
- `PhysicalResourceProvider` owns only `realize`, `observe`, and `retire`. It never decides placement, reuse, ownership, generation, lease validity, or fencing.
- Observations are evidence, never authority. An observation can bind only the exact current ticket, resource key, generation, provider kind, and realization-spec digest.
- Realization is single-flight per semantic realization key. Crash recovery replays the same stable ticket; PREPARED plus an exact-ticket physical effect is recoverable without inventing a new generation.
- Retirement order is: logical fence, physical retire, observed-absent confirmation, then capacity/claim release. Capacity is never advertised while an unproven physical consumer may still exist.
- Endpoint reservation is a claim over a host/port token. Listener readiness is Provider/session evidence and cannot silently mutate endpoint ownership.
- Compute inventory, GPU/host pressure probes, endpoint candidate sources, and socket probes are read-only fact sources. They are not lifecycle authorities.
- Runtime Fabric and recovery ownership use Authority leases directly. There is no parallel `ResourceLeaseRegistry`, endpoint allocation authority, compute scheduler authority, Docker lease authority, or environment-instance lease authority.
- SQLite durability belongs to the Authority transaction boundary. Provider location, operating system, or process restart cannot weaken fencing or transition atomicity.

The research/resource graph carries dependency structure and stable authority keys. `ResourceGraph` is a projection of `NoetriumGraph`; it is not a second lifecycle database. Reconciliation derives acquire and reverse-retire order from the graph and converges the Authority plus physical Providers to the desired topology.
