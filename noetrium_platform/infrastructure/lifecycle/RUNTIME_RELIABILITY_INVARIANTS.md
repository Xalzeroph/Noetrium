# Runtime & Reliability Invariants

This document records ROLE 02 runtime invariants that are enforced directly by the production contracts in `noetrium_platform/infrastructure/lifecycle`, `noetrium_platform/infrastructure/resources`, and `noetrium_platform/infrastructure/reliability`.

## Process-command ownership

`ProcessCommandRunnerPort.execute` accepts only a finite positive `timeout_seconds`. The timeout is an end-to-end command budget: structured ASYNC_IO admission is deadline-bound, process execution uses only the budget that remains after admission/spawn, and a separate cleanup reserve is retained so timeout or cancellation can terminate and reap the owned process tree before normal completion is reported.

Callers must wait on the owned task handle itself rather than impose a second `Future.result(timeout=...)` deadline. A detached caller deadline can return failure while the structured task remains eligible to start later, which is forbidden for external effects. `ProcessSupervisorPort.await_exit` and `terminate` likewise require an explicit structured `Deadline`; queue admission and process polling must never exist without a terminal owner budget.

## SSH and remote-operation bounds

Automated SSH commands, SCP transfers, repository operations, and foreground interactive SSH/tmux attaches all have finite profile budgets. Interactive attaches use `ServerConnectionProfile.interactive_timeout_seconds` (environment key `RP_SERVER_<ID>_SSH_INTERACTIVE_TIMEOUT_SECONDS`) rather than an unbounded process wait. The interactive budget is identity-bearing and is included in the composed server profile digest.

## Effect certainty

A timeout, cancellation, network loss, process ownership loss, or other failure after a mutating server operation has been journaled must never be interpreted as `NO_EFFECT`. The server operation ledger keeps such operations effect-uncertain until typed reconciliation evidence resolves the original operation identity. New mutations remain fenced while an unreconciled effect exists.

## Validation expectation

Changes to these invariants require focused Windows tests plus Linux validation for POSIX process-group cleanup and SSH/process behavior. Server validation must use the designated Platform validation host; protected SEM runtime directories, GPU allocations, and model-serving endpoints are outside this subsystem's validation authority.

## Finite temporal controls

Every externally configurable runtime duration that can bound admission, cleanup, polling, transport, process execution, session control, toolchain acquisition, or operational GPU observation must be finite and strictly positive before any external action begins. `NaN`, positive/negative infinity, zero, and negative durations are configuration errors rather than alternate timeout semantics.

This applies to process cleanup/default/override timeouts, service readiness/stop/heartbeat values, readiness poll/request budgets, SSH connect/control/command/interactive/transfer/repository/Git budgets, tmux command budgets, Java runtime acquisition, and `nvidia-smi` observation commands. Typed outer deadlines remain authoritative; component-local timers may only consume a finite portion of that budget and cannot disable it.


## Server-operation journal integrity

Remote-operation history is a corruption-sensitive WAL, not diagnostic text. Each persisted event uses schema `server-operation-journal.v2`, carries the previous record checksum, and carries its own SHA-256 checksum over canonical bytes. Replay begins from a fixed genesis checksum and fails closed on malformed JSON, legacy unchecksummed rows, checksum mismatch, chain discontinuity, partial tails, oversized rows, unexpected fields, primitive-type drift, or semantically invalid event transitions.

The same strict decoder validates an event before append so production cannot durably publish a record that recovery would later reject. New journal-file publication fsyncs the file and then its parent directory; later appends fsync the file while preserving the existing short interprocess append lock. Full-prefix verification remains outside the writer lock, and append finds only the last chain head under the lock, so integrity does not restore O(file-size) writer serialization.


## Durable server-operation evidence semantics

Server-operation WAL records reject unsafe durable identities and non-canonical request/profile/output/error digests before publication. Persisted success must prove `return_code=0` with `failure_kind=none`; timeout must carry `failure_kind=timeout`; failed records cannot claim a success failure-kind; and exception type/digest evidence is all-or-nothing. These invariants apply at the durable codec boundary so in-memory diagnostic projections remain independent from WAL identity requirements.

## Authoritative readiness time

- A service READY transition persists its producer-observed `ready_at` independently from `last_heartbeat_at`.
- The Runtime-owned `LocalServiceProcessAdapter` is the readiness receipt authority: immediately after the endpoint/process readiness probe returns success, it freezes contract digest, exact process identity, readiness ref, capture refs, and epoch `ready_at` into immutable `ServiceReadyEvidence`.
- `ServiceReadinessCommitter` accepts only that typed receipt, rejects contract/process rebinding, and has no wall-clock authority of its own.
- `ready_at` is finite, positive, immutable for that process generation, and is cleared before a new child generation starts.
- Heartbeats may advance `last_heartbeat_at` but must never rewrite the original readiness authority.
- `ServiceStartOutcome` and `ServiceReadyObservation` project the exact persisted `ready_at`; consumers must not synthesize a replacement wall-clock timestamp.
- Durable service-state codec v3 fails closed when readiness evidence and readiness time are incomplete or non-finite.

## Forensic directory-entry mutation authority

- Linux segmented-ledger ownership uses inotify; Windows uses `FindFirstChangeNotificationW` / `WaitForSingleObject` / `FindNextChangeNotification` for file/directory-name changes.
- Windows must not treat directory `stat()` metadata as authoritative because fresh child creation can leave the observed directory metadata unchanged.
- Kernel directory-entry signals keep steady-state append O(1): no segment-directory enumeration is introduced on the hot path.
- Any unacknowledged create/delete/rename signal fails closed before append and forces full ledger verification; writer-owned changes are acknowledged only after the owned append completes.
- The segmented writer returns an internal append receipt and creates new segment files exclusively; a signal observed after an ordinary active-file append is never acknowledged as writer-owned.
- When an append legitimately creates a segment, the slow path may boundedly wait up to 250 ms for the same kernel notification handle, then verifies the exact owned directory namespace before consuming the expected notification; notification timeout still fails closed, and coalesced external entries cannot hide behind rotation.
- Failure to create, wait on, advance, or close the Windows notification handle is surfaced rather than silently degrading to the nondeterministic stat fallback.
- Managed server health preflight must probe Linux inotify watch registration as a read-only OS authority fact. It reports `inotify_watch_authority=available|unavailable` (`not_required` off Linux), immediately closes the probe fd, and treats `unavailable` as `platform_ready=False` with stable diagnostic code `health:inotify_watch_authority`; doctor/preflight must never infer readiness from sysctl limits alone or silently substitute directory `stat()`.

## Scaffold contraction

ROLE02 semantic authorities live in the substantive Runtime, Resource, and Reliability parent APIs/runtimes, not in generated `SystemLeafContract` shells. Semantic-density contraction therefore retires redundant child packages for diagnostic causal/timeline labels, failure facets, incident/policy/reconciliation labels, recovery evidence/plan/replay labels, resource catalog, Runtime control/history, process identity/launch/lifecycle, session binding/identity, and top-level supervision.

The contraction must not move or duplicate authority. Process lifecycle remains in `runtime.process` / `runtime.process.supervision`; session identity and binding remain in `runtime.session`; causal diagnostics remain in `reliability.diagnostics`; failure taxonomy/catalog/fingerprint/envelope semantics remain in `reliability.failure`; uncertain-effect/recovery semantics remain in `reliability.effect` and `reliability.recovery`; live Resource truth remains in compute/lease/allocation/resolution authorities.

Governance catalog retirement is ROLE01-owned and Release manifest regeneration is ROLE06-owned. A producer-side deletion may therefore require a coordinated catalog/release cut, but no empty package may be recreated merely to satisfy stale node-cardinality assertions.

## Read-only compute preflight

Runtime/Research Compiler/doctor preflight consumes Resource capacity through `ComputeCandidatePort` assembled by explicit composition; it must not duplicate scheduler filtering logic. `candidates()` is a read-only projection over current scheduler usage, so existing allocations may remove a host from the candidate set without granting preflight allocate/release authority. Candidate reads must leave allocation truth unchanged.
