# Lifecycle OS v18

Every long-lived subsystem has an explicit lifecycle instead of relying on constructor/destructor ordering.

States: `NEW -> STARTING -> READY -> STOPPING -> STOPPED`, with `FAILED` explicit.

`LifecycleManager` validates all component IDs/dependencies and computes a deterministic topological startup order **before any start side effect**. A missing dependency or cycle therefore cannot leave a partially started platform. If a component fails to start, already-started components are stopped in exact reverse order. Rollback failures are preserved separately from the original start failure.

Health is distinct from lifecycle. A component may remain in `READY` but be classified `STALLED` when its heartbeat or progress heartbeat expires. Health records include generation, PID + process-start identity, heartbeat/progress time, last failure and a compact resource snapshot. This supports precise differentiation among:

- process dead;
- process alive but heartbeat dead;
- heartbeat alive but scientific/work progress stalled;
- component explicitly failed;
- component intentionally stopped.

No health classification silently selects another model, method, precision, context size or prompt.

## Process-supervision task identity

Every `AsyncProcessSupervisor` owns an instance-level structured-concurrency task namespace. Per-operation sequence numbers are unique only inside that namespace; they are not assumed to be globally unique across supervisor objects. This prevents multiple service/bridge supervisors sharing one `TaskGroup` from colliding when they supervise the same logical role. The namespace is runtime ownership metadata and does not alter scientific run/process identity.

## Structured deadline propagation

A task that is the first observer of an inherited `TaskGroup` deadline is responsible for linearizing group cancellation before it returns a logical deadline outcome. `TaskContext.wait()` distinguishes a caller timeout from a deadline-limited wait; when the group deadline expires it cancels the owning group and sibling tasks observe `TaskCancelled` rather than continuing past the expired scope.

This contract is independent of timer-worker scheduling. Delaying the group watchdog must not allow a sibling task to complete successfully after another child has already observed the group deadline. Release qualification stress-tests this path under concurrent shard load.

## Runtime filesystem snapshot discipline

Process capture initialization freezes the ordered segment names and sizes with
one directory scan. The writer derives its recovered total, active segment index
and active size from that snapshot instead of independently globbing/statting the
same capture directory for each field. Full segment hashing remains mandatory for
capture verification; integrity I/O is not skipped merely to improve latency.

On Linux, one `LinuxProcessFacts` observation resolves the visible `/proc/<pid>`
directory once and reads stat, executable, argv, cwd and environment from that
same directory identity. This matters under nested PID namespaces, where resolving
a namespace-local PID may require scanning `status:NSpid` across procfs. A single
facts observation must not repeat that global scan for each field.
