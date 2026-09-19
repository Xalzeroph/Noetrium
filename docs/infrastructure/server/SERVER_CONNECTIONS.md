# Server Connection Contract

The platform server layer models a remote host as an explicit `server_id` plus a complete connection/runtime profile. It does not ship with a fleet catalogue.

A deployment or downstream project selects its own server IDs and provides profile values outside the reusable source tree. The platform parses and validates those values; it does not guess hostnames, users, ports, paths, toolchains, or credentials.

## Profile naming

For a server ID such as `server-a`, the environment prefix is derived mechanically as `RP_SERVER_SERVER_A_...`. Fleet membership is explicit through `RP_SERVER_CATALOG_IDS`.

The checked-in example [`../../../configs/server_profiles/server.example.env`](../../../configs/server_profiles/server.example.env) documents the supported fields without selecting any real machine.

## Authentication

Prefer an SSH key or agent for unattended operations. Passwords and private keys are never committed. Local SSH configuration and control-socket paths remain operator-local.
## Runtime and path identity

Remote filesystem roots, interpreter/toolchain paths, session configuration, and repository roots are part of the deployment profile because they affect reproducibility and mutation safety. A downstream deployment may pin executable digests when exact toolchain attestation is required.

Command execution, file transfer, repository operations, and persistent sessions have independent timeout/budget controls. Server operations are journaled with typed observation/mutation intent so retries do not silently duplicate uncertain external effects.

## Durable operation lifecycle

Managed SSH/SCP effects are recorded in an append-only server-operation ledger. Each operation id has one legal durable lifecycle:

```text
STARTED -> FINISHED
   |
   +------> RESOLVED   (only while the external effect is uncertain)
```

`record_started`, `record_finished`, and `record_resolved` are transition-safe writes. A per-operation interprocess transition lock fences concurrent controllers before they inspect the current record and append the next event. A duplicate finish, duplicate resolution, finish after reconciliation, or profile/request/effect identity drift raises `ServerOperationTransitionConflict` **before** the ledger is modified. The short global append lock remains responsible only for byte ordering and fsync, so unrelated operation ids do not share a long lifecycle lock.

Replay independently revalidates the same state machine. Corrupt or externally edited records fail closed with `ServerOperationJournalIntegrityError`; replay is not used as permission for a writer to append an illegal transition. A resolution proves only the disposition of a previously uncertain server operation. It is not scientific evidence and does not authorize a blind retry.

The JSONL ledger is the Runtime operation-history authority, not current remote process truth. Live state must be reconciled through the server/process runtime ports. Reliability effect/reconciliation contracts remain a cross-system seam and must not be duplicated by adding a second generic effect authority inside Runtime.

## Repository boundary

Concrete machine inventories and their current state belong in the downstream deployment repository or an ignored operator inventory. They must not be added to this upstream document, the generic README, or the platform release manifest.

## OpenSSH provider boundaries

The OpenSSH implementation is decomposed by responsibility rather than file size.
Environment materialization owns only `ServerConnectionProfile` construction and
local file/config validation. `OpenSSHArgumentPolicy` is a pure argv policy shared
by SSH and SCP and performs no process launch or durable write.

`SSHServerConnection` owns command/interactive transport semantics but delegates
process creation, cancellation, timeout, capture and process-tree reaping to the
injected process-supervision port. `SSHServerFileTransfer` owns SCP transfer
semantics and local download publication; successful downloads are first written
to a temporary path and only then durably replace the authoritative local target.

The public provider exports remain the typed connection/file-transfer factories and
ports. There is no `providers.ssh` compatibility facade: internal responsibility
changes must not become a second public contract. Host OS routing remains an
explicit composition requirement; this refactor does not infer or replace that
authority.

## Catalog namespace identity

`server_environment_prefix()` normalizes logical IDs for environment keys, so the
catalog validates the resulting namespaces before reading any server fields. Two
IDs whose normalized prefixes collide, or where one declared namespace prefixes
another, are rejected. This prevents one server from inheriting another server's
configuration merely because their environment-key spellings overlap.

Catalog construction indexes the declared prefixes once and assigns each
`RP_SERVER_*` key in one pass. Membership validation therefore scales with the
profile text rather than repeatedly rescanning every environment key for every
server.
