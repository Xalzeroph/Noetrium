from __future__ import annotations

import threading
from concurrent.futures import CancelledError
import unittest

from noetrium_platform.composition.environment_capability_runtime import (
    LocalEnvironmentPortfolioRuntime,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
)


class _BaseFailingClose:
    def close(self) -> None:
        raise BaseExceptionGroup(
            "inner base failure",
            [KeyboardInterrupt("synthetic cancellation")],
        )


class _CleanClose:
    def close(self) -> None:
        return None


class _DeferredPreparation:
    def __init__(self) -> None:
        self.cancelled = False
        self.materialized = False

    def cancel(self) -> bool:
        self.cancelled = True
        return True

    def result(self, timeout=None):
        del timeout
        if self.cancelled:
            raise CancelledError()
        self.materialized = True
        return None

    def done(self) -> bool:
        return self.cancelled or self.materialized


class EnvironmentCleanupBaseExceptionGroupTests(unittest.TestCase):
    def test_minecraft_close_cancels_pending_preparation_before_join(self) -> None:
        controller = object.__new__(LocalMinecraftLifetimeSessionController)
        controller.lock = threading.RLock()
        pending = _DeferredPreparation()
        controller._preparations = {"pending-lifetime": pending}
        controller._preparation_failures = {}
        controller.runtimes = {}
        controller._lifetime_locks = {}
        controller._retirements = {}
        controller._retirement_rows = {}
        controller._retirement_failures = {}
        controller._runtime_gc_handles = []
        controller._capsule = _CleanClose()
        controller._reconcile_shared_fabric = lambda: None

        controller.close()

        self.assertTrue(pending.cancelled)
        self.assertFalse(pending.materialized)
        self.assertEqual(controller._preparations, {})
        self.assertEqual(controller._preparation_failures, {})

    def test_minecraft_cleanup_preserves_base_exception_group(self) -> None:
        controller = object.__new__(LocalMinecraftLifetimeSessionController)
        controller.lock = threading.RLock()
        controller._preparations = {}
        controller._preparation_failures = {}
        controller.runtimes = {}
        controller._lifetime_locks = {}
        controller._retirements = {}
        controller._retirement_rows = {}
        controller._retirement_failures = {}
        controller._runtime_gc_handles = []
        controller._capsule = _BaseFailingClose()

        with self.assertRaises(BaseExceptionGroup) as caught:
            controller.close()

        self.assertIn("Minecraft lifetime cleanup failed", str(caught.exception))
        self.assertNotIsInstance(caught.exception, TypeError)

    def test_environment_portfolio_can_aggregate_base_exception_group(self) -> None:
        runtime = LocalEnvironmentPortfolioRuntime(
            port=None,
            lifetime=None,
            runtimes=(("program-a", _BaseFailingClose()),),
            physical_runtimes=(),
            effect_journal=_CleanClose(),
        )

        with self.assertRaises(BaseExceptionGroup) as caught:
            runtime.close()

        self.assertIn("environment portfolio runtime close failed", str(caught.exception))
        self.assertTrue(runtime._closed)


    def test_environment_portfolio_delegates_physical_retirement_to_execution_pool(self) -> None:
        retired: list[object] = []

        class Pool:
            def retire_lifecycle_resource(self, resource: object) -> None:
                retired.append(resource)

        class Physical:
            def __init__(self) -> None:
                self.execution_pool = Pool()
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        physical = Physical()
        runtime = LocalEnvironmentPortfolioRuntime(
            port=None,
            lifetime=None,
            runtimes=(),
            physical_runtimes=(physical,),
            effect_journal=_CleanClose(),
        )

        runtime.close()

        self.assertEqual(retired, [physical])
        self.assertEqual(physical.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
