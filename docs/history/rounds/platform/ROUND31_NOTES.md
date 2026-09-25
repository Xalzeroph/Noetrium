# Round 31 — Exact Runtime Operability

- Every runtime control-state write now appends to a hash-chained transaction history.
- Added exact service heartbeat records bound to deployment stack digest, process identity and qualification evidence.
- Added explicit crash classification for OOM, GPU Xid, signal, heartbeat loss, service error and unknown failure.
- Added exclusive recovery lease so two operators/processes cannot resume the same frozen run concurrently.
- Added `OneClickRuntimeManager`: verify transaction history -> hold recovery lease -> exact runtime transaction -> reverify history -> release lease.
- Existing runtime plan still requires exact release, prompt promotion, host inventory, deployment identity, readiness, role canaries, method/environment ABI and exact study reconciliation before resume.
- No model replacement, precision reduction, context reduction, prompt substitution or silent quality downgrade is permitted.
