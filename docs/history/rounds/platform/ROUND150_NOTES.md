# Platform Round 150 Notes

Date: 2026-08-30

## Deadline/cancellation race closure

`_OwnedTaskHandle.result()` now preserves the logical deadline authority when the provider future is cancelled during the tiny residual wait after an initial bounded `Future.result()` timeout. The residual branch reconciles the task record and surfaces `TaskDeadlineExceeded` when the deadline watcher has already committed that failure, instead of leaking provider-level `concurrent.futures.CancelledError`.

A deterministic regression uses a fake raw handle that times out on the first wait and cancels on the residual wait, reproducing the exact race window without scheduler timing dependence.

## Verification

Verification results are recorded in the ROLE01 handoff for the exact candidate containing this fix.

## Async source-task terminal ownership closure

The async I/O provider now distinguishes logical cancellation from physical coroutine completion. Cancelling a provider handle requests cancellation of the source `asyncio.Task`, but does not mark the provider proxy complete or release `max_in_flight` capacity until that source task has actually reached its terminal state.

The provider-owned done callback retrieves the source task result or exception before publishing the proxy outcome. This prevents `Task exception was never retrieved` when a caller has already observed a logical deadline and also prevents a second async task from entering while the cancelled predecessor is still performing physical cleanup.

New regressions prove that a cancellation-suppressing coroutine retains the sole capacity slot through cleanup, and that a source task ending in a domain exception after cancellation is retrieved by the provider even when the caller never reads the proxy result.

## Shutdown join and cancellation idempotency

Repeated cancellation requests are now idempotent: once source-task cancellation has been requested, later `cancel()` calls do not inject another `asyncio` cancellation into cleanup. A `close(wait=True)` that follows an earlier non-blocking close joins the already-owned shutdown instead of stopping the event loop before physical task completion.

The deterministic shutdown regression proves cancellation cleanup reaches completion, the loop thread terminates, and no `Task was destroyed but it is pending!` event-loop diagnostic is emitted.
