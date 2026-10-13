from __future__ import annotations

from noetrium_platform.composition.concurrency import build_scheduling_authority

from dataclasses import dataclass
from threading import RLock
from tempfile import TemporaryDirectory
from pathlib import Path
import types
import unittest

from noetrium_platform.composition.concurrency import (
    build_execution_concurrency_runtime,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
)


@dataclass(frozen=True)
class _Context:
    lifetime_id: str
    run_id: str
    experiment_id: str = "experiment-a"


class _Control:
    group_id = "prewarm-probe"
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
        """This test's non-cancelling control registers an inert subscription."""
        return lambda: None


class MinecraftPrewarmCompletionPropagationTests(unittest.TestCase):
    def test_worker_publish_wakes_prepare_barrier(self) -> None:
        runtime = build_execution_concurrency_runtime(scheduling_authority=build_scheduling_authority(),)
        group = runtime.open_task_group("minecraft-prewarm-probe")
        controller = object.__new__(LocalMinecraftLifetimeSessionController)
        controller.lock = RLock()
        controller.runtimes = {}
        controller._retirements = {}
        controller._retirement_rows = {}
        controller._preparations = {}
        controller._preparation_failures = {}
        controller._retirement_failures = {}
        controller._lifetime_locks = {}
        controller.prewarm_task_group = group
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

        try:
            controller.prepare(context, control)
            self.assertIn("lifetime-a", controller.runtimes)
            self.assertEqual(controller._preparations, {})
            self.assertEqual(controller._preparation_failures, {})
        finally:
            runtime.close_task_group(group)
            runtime.close()
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
