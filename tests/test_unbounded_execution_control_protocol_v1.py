from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    UNBOUNDED_EXECUTION_CONTROL,
)


def test_unbounded_control_fulfills_full_cancellation_port_without_polling() -> None:
    control = UNBOUNDED_EXECUTION_CONTROL
    assert isinstance(control, ExecutionControlPort)
    called = []
    unsubscribe = control.subscribe_cancel(lambda: called.append("cancel"))
    assert callable(unsubscribe)
    unsubscribe()
    assert called == []
    assert control.cancelled is False
    assert control.remaining_seconds is None
    control.checkpoint()


def test_unbounded_control_rejects_noncallable_cancellation_subscription() -> None:
    with pytest.raises(TypeError, match="callable"):
        UNBOUNDED_EXECUTION_CONTROL.subscribe_cancel(None)
