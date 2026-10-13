from __future__ import annotations

from noetrium_platform.composition.research_graph import _AttemptTaskContext
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    UNBOUNDED_EXECUTION_CONTROL,
)


class _Underlying:
    group_id = "group"
    task_id = "raw-task"
    lane_kind = "blocking_io"
    deadline = None
    remaining_seconds = None
    cancelled = False
    reason = None

    def __init__(self):
        self.callbacks = []

    def wait(self, timeout=None):
        return False

    def checkpoint(self):
        return None

    def subscribe_cancel(self, callback):
        self.callbacks.append(callback)
        def unsubscribe():
            self.callbacks.remove(callback)
        return unsubscribe


def test_graph_attempt_context_preserves_cancellation_authority_and_identity() -> None:
    underlying = _Underlying()
    ctx = _AttemptTaskContext(underlying, "durable-attempt-id")
    assert isinstance(ctx, ExecutionControlPort)
    assert ctx.task_id == "durable-attempt-id"
    assert ctx.group_id == "group"
    observed = []
    cancel = ctx.subscribe_cancel(lambda: observed.append("cancelled"))
    assert len(underlying.callbacks) == 1
    underlying.callbacks[0]()
    assert observed == ["cancelled"]
    cancel()
    assert not underlying.callbacks


def test_graph_attempt_context_composes_with_unbounded_execution_control() -> None:
    # Narrow task/attempt wrapper must not break the full structural port.
    ctx = _AttemptTaskContext(UNBOUNDED_EXECUTION_CONTROL, "durable")
    assert isinstance(ctx, ExecutionControlPort)
    cancel = ctx.subscribe_cancel(lambda: None)
    cancel()
