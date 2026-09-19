# Minecraft Endpoint Generation Binding

Minecraft branch endpoints are process-generation evidence, not merely reserved host/port pairs. A branch server restart therefore requires a new binding proof even when the address is unchanged.

## Authority flow

The branch runtime owns one typed `MinecraftServerEndpointBindingPort`. The same authority is passed to initial branch startup and to the branch checkpoint provider so every server generation is published through one state machine.

- Initial server READY: `RESERVED -> BOUND` through `confirm_bound`.
- Exact replay of the same READY proof: idempotent `confirm_bound`.
- New process generation on the same endpoint: `BOUND -> BOUND` through `replace_bound` using the previous binding-proof digest as CAS authority.
- Final branch close: `BOUND -> RELEASED` through the endpoint allocator.

Game and RCON allocations are advanced from the same READY process evidence. If either binding cannot be advanced, checkpoint restore/recovery cannot claim success.

## Readiness time authority

`EndpointBindingProof.observed_at_epoch_s` is copied directly from `ServiceReadyObservation.ready_at`. Environment code must never substitute a local `time.time()` sample.

The Environment boundary admits only an actual typed `ServiceReadyObservation`; a shape-compatible object carrying the same attributes is rejected before binding.

The readiness timestamp is part of the proof digest. Consequently, repeated verification of the same process generation must reproduce the persisted producer timestamp; otherwise the proof would drift despite an unchanged binder identity.

ROLE05 therefore fails closed when `ready_at` is missing, boolean, non-finite or non-positive. The required producer semantics are owned by runtime/reliability; ROLE05 only consumes the typed evidence.

## Checkpoint restart invariant

A branch checkpoint restore may stop and restart the Java server while preserving the endpoint address. After each successful `verify_ready()`—both normal restore and crash rollback recovery—the checkpoint provider must call the shared endpoint-binding authority before publishing restore completion.

This ordering prevents three invalid states:

1. restored world committed while Resource still names the pre-restore Java process;
2. rollback recovery reported complete while Resource names the failed restore process;
3. game and RCON endpoint evidence remaining on different server generations without surfacing an error.

A rebind failure participates in restore failure handling. The restore journal remains authoritative until filesystem recovery and endpoint-generation publication are both complete.

## Cross-system dependency

The consumer requires the Resource generation-replacement contract introduced by ROLE02 commit `ebb50fc679267bbfa7179a56b5d49214341a24c7` (`EndpointAllocationPort.replace_bound`).

It also requires a runtime producer that records `ServiceReadyObservation.ready_at` at the readiness-producing seam and reuses that exact persisted value on later verification. A field populated later by a consumer-side wall-clock sample is not sufficient for proof identity.

Integration order is therefore ROLE02 producer contract first, ROLE05 Minecraft consumer second. Missing producer authority is an integration blocker, not a reason for an Environment fallback clock.