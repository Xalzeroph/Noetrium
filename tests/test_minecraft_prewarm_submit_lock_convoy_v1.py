from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
import types
import unittest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort


@dataclass(frozen=True)
class _Context:
    lifetime_id: str
    run_id: str
    experiment_id: str = "experiment-a"


class _Control:
    group_id = "prewarm-submit-convoy"
    task_id = "caller"
    lane_kind = None
    deadline = None
    remaining_seconds = None
    cancelled = False
    reason = None

    def checkpoint(self) -> None:
        return None

    def wait(self, timeout=None) -> bool:
        return False

    def subscribe_cancel(self, callback):
        del callback
        return lambda: None


class _ImmediateHandle:
    def __init__(self, fn) -> None:
        self._fn = fn
        self._done = False

    def done(self) -> bool:
        return self._done

    def add_done_callback(self, callback) -> None:
        if not self._done:
            self._fn(_Control())
            self._done = True
        callback(self)

    def result(self, timeout=None):
        if timeout is not None and timeout > 0.0:
            raise AssertionError(
                f"prewarm completion must not poll TaskHandle.result: {timeout!r}"
            )
        if not self._done:
            raise AssertionError("result read ran before physical completion")
        return None


class _BlockingSubmitGroup:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def submit(self, _spec, fn):
        self.entered.set()
        if not self.release.wait(3.0):
            raise TimeoutError("fixture did not release blocked submit")
        return _ImmediateHandle(fn)


class MinecraftPrewarmSubmitLockConvoyTests(unittest.TestCase):
    def test_blocked_admission_submit_does_not_hold_controller_lock(self) -> None:
        controller = object.__new__(LocalMinecraftLifetimeSessionController)
        controller.lock = RLock()
        controller.runtimes = {}
        controller._retirements = {}
        controller._retirement_rows = {}
        controller._preparations = {}
        controller._preparation_failures = {}
        controller._retirement_failures = {}
        controller._lifetime_locks = {}
        controller.prewarm_task_group = _BlockingSubmitGroup()
        controller.owner_generation_id = "probe-generation"

        temporary = TemporaryDirectory()
        controller.state_root = Path(temporary.name)
        session = object()

        def fake_session_for(self, context):
            with self.lock:
                self.runtimes[context.lifetime_id] = types.SimpleNamespace(
                    session=session
                )
            return session

        controller.session_for = types.MethodType(fake_session_for, controller)
        context = _Context("lifetime-a", "run-a")
        control = _Control()
        self.assertIsInstance(control, ExecutionControlPort)
        outcome: list[BaseException | None] = []

        def run_prepare() -> None:
            try:
                controller.prepare(context, control)
            except BaseException as exc:
                outcome.append(exc)
            else:
                outcome.append(None)

        thread = Thread(target=run_prepare, daemon=True)
        thread.start()
        self.assertTrue(controller.prewarm_task_group.entered.wait(1.0))

        acquired = controller.lock.acquire(timeout=0.2)
        if acquired:
            controller.lock.release()

        controller.prewarm_task_group.release.set()
        thread.join(3.0)
        temporary.cleanup()

        self.assertTrue(
            acquired,
            "blocked prewarm admission submit held the global controller lock",
        )
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [None])
        self.assertIn("lifetime-a", controller.runtimes)


if __name__ == "__main__":
    unittest.main()
