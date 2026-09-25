# Round 143 — server-doctor structured-concurrency binding

Date: 2026-08-28

## Change

`server_doctor inspect` now opens the shared server CLI concurrency scope and injects the resulting `TaskGroup` into `compose_server_from_environment`.

This removes an implicit execution-owner gap: health/session/operation inspection now composes the server through the same structured-concurrency authority used by the rest of the server control plane instead of allowing leaf process work to create an unowned execution route.

## Boundary

The doctor remains read-only. The TaskGroup does not authorize mutation, retry, recovery or credential discovery; it only owns deadlines, cancellation and child execution identity for the diagnostic command lifetime.

## Verification

`tests/test_server_doctor_concurrency_v1.py` proves the exact CLI task group is passed into server composition. Real fleet observations recorded in Rounds 139–140 also reported both managed servers reachable and mutation-ready with no pending operations.
Live controller verification after the code change inspected both managed online nodes with the current `server_doctor`: both returned exit `0`, `platform_ready=true`, `ready_for_mutation=true`, and no pending operations.

Server 2 also emitted a non-blocking shell-profile warning for a missing `~/.local/bin/env`; that profile debt remains visible and does not replace the attested explicit Python/Node/Java toolchain paths.
