# Service OS v19

Model serving, Study and environment services should share one supervisor contract instead of bespoke shell behavior.

A `ServiceLaunchContract` freezes executable, argv, cwd, environment digest, artifact digest, runtime-identity digest, generation and timing parameters. Recovery/restart is allowed only against that exact digest.

Supervisor phases are explicit:

`VERIFY_CONTRACT -> RECONCILE_PRIOR -> START_CHILD -> WAIT_READY -> RUNNING -> STOPPING/FAILED/RECOVERY_REQUIRED`.

A process PID is never sufficient identity; the adapter returns `pid + process_start_identity (+ pgid)` and must reconcile that tuple before reuse/termination. READY is re-proven even when an exact existing process is reconciled.

`ServiceExitClass` follows stable sysexits-style semantics:

- 0 CLEAN
- 70 SOFTWARE
- 74 IO_ERROR
- 75 TEMPORARY
- 78 CONFIGURATION

Only TEMPORARY may request an automatic **same-contract** restart, under a bounded restart window. There is no smaller model, lower precision, shorter context, simplified prompt or alternative method path.

The systemd renderer is deliberately dumb: it only renders an already frozen launch command. `RestartPreventExitStatus=70 74 78`; systemd does not make model/resource decisions.
