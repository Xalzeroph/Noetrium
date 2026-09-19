# Round 146 — deadline propagation release hardening

Date: 2026-08-28

## Trigger

The machine-readable release regression exposed a race that did not reproduce in the ordinary full-suite run. When the timer worker was deliberately delayed, one child could observe the inherited `TaskGroup` deadline while a sibling waiting on the same scope returned before group cancellation became visible.

## Change

`TaskContext.wait()` now distinguishes user timeout from a wait bounded by the inherited deadline. The child that first observes an expired group deadline linearizes group cancellation before returning, so siblings cannot escape the expired scope as successful work merely because the timer watchdog is delayed.

The pressure test cleanup also releases its deliberately blocked timer before closing the task group/runtime, ensuring an assertion failure cannot strand a timer worker and inflate a release shard into a timeout.

## Verification

The exact deadline race passed 50 independent process-level repetitions (`DEADLINE_STRESS_PASS=50/50`). The complete platform concurrency runtime test module then passed 37/37.

This change preserves the distinction between logical cancellation and physical structured convergence; `close()` still joins owned execution before claiming a clean shutdown.
