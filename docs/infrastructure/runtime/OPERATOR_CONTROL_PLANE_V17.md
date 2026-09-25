# Operator Control Plane v17

The operator surface is one read-mostly control plane: `noetrium-forensics`.

Core commands:

- `verify-evidence RUN_ROOT`: cryptographically verify failures/events/mutations.
- `why RUN_ROOT FAILURE_ID --graph`: root-cause summary plus explicit-reference causal graph.
- `locate RUN_ROOT OBJECT_ID`: resolve opaque IDs.
- `timeline RUN_ROOT OBJECT_ID`: time-correlated evidence; proximity is never labeled causality.
- `last-writer RUN_ROOT RUN_ID STATE`: exact authoritative state writer.
- `crash-bundle RUN_ROOT FAILURE_ID OUTPUT`: immutable compact crash manifest.
- `telemetry-query DB RUN_ID`: raw high-cardinality rows from a strictly read-only SQLite connection.
- `telemetry-summary DB RUN_ID METRIC`: min/max/mean/p50/p95/p99 from raw rows.
- `recovery-state PATH`: inspect a crash-reconcilable exact-recovery transaction without mutating it.
- `release-verify ROOT RELEASE_MANIFEST.json`: verify every release byte.
- `architecture-report SOURCE_ROOT`: physical import graph, cycles, authority violations and hotspots.
- `architecture-gate`: CI/operator architecture gate.

Expected operator errors are emitted as JSON with a non-zero exit code. Unexpected programming errors still escape with a traceback; they are not disguised as operational failures.

## Causality rule

The graph builder only emits causal/reference edges from explicit IDs and references (`operation_id`, component, request/effect/artifact/state refs, task/trace/span ownership). Objects retrieved merely because they are temporally or contextually related are added as nodes but are **not** given a causal edge unless an explicit relation exists.

## Read-only semantics

Operator queries never append or rewrite authoritative failure/event/mutation chains, telemetry rows, durable recovery state, or the main forensic SQLite database. SQLite in WAL mode may create/delete its disposable `-shm`/empty `-wal` coordination sidecars when a read-only process attaches; these files are not authoritative evidence and are excluded from evidence identity. The main DB bytes and authoritative ledgers remain unchanged.
