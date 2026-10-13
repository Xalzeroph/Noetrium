from __future__ import annotations

from collections import Counter
from threading import Event, RLock, Thread
from types import SimpleNamespace
import time
import unittest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
)
from noetrium_platform.foundation.scope.api import ScopeKind, scope_unit


class _Guard:
    def __init__(self, row) -> None:
        self.handles = (row,)
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


class _GuardFactory:
    def create(self, rows):
        self_row, = tuple(rows)
        return _Guard(self_row)


class _Authority:
    def __init__(self, *, block_first_run: bool = False) -> None:
        self.calls = Counter()
        self.released = []
        self.block_first_run = block_first_run
        self.run_entered = Event()
        self.run_release = Event()

    def acquire_scope_lease(self, *, scope, **_kwargs):
        kind = str(scope.attribute("scope_kind"))
        self.calls[kind] += 1
        ordinal = self.calls[kind]
        if kind == ScopeKind.RUN.value and self.block_first_run and ordinal == 1:
            self.run_entered.set()
            if not self.run_release.wait(3.0):
                raise TimeoutError("fixture did not release run-scope authority call")
        return SimpleNamespace(kind=kind, ordinal=ordinal)

    def release_lease(self, row) -> None:
        self.released.append(row)


def _controller(authority: _Authority):
    controller = object.__new__(LocalMinecraftLifetimeSessionController)
    controller.lock = RLock()
    controller.resource_authority = authority
    controller.resource_lease_guard_factory = _GuardFactory()
    controller.owner_generation_id = "owner-generation"
    controller._run_scope_guards = {}
    controller._run_scope_refcounts = {}
    controller._run_scope_experiments = {}
    from threading import Condition
    controller._run_scope_condition = Condition(controller.lock)
    controller._run_scope_transitions = set()
    return controller


def _context(lifetime_id: str):
    return SimpleNamespace(
        experiment_id="experiment-a",
        run_id="run-a",
        lifetime_id=lifetime_id,
    )


class MinecraftRunScopeLockConvoyTests(unittest.TestCase):
    def test_slow_authority_call_does_not_hold_controller_metadata_lock(self) -> None:
        authority = _Authority(block_first_run=True)
        controller = _controller(authority)
        branch = scope_unit(ScopeKind.BRANCH, "branch-a")
        outcome = []

        def acquire() -> None:
            try:
                outcome.append(
                    controller._acquire_branch_scope_lease(
                        _context("lifetime-a"),
                        branch,
                    )
                )
            except BaseException as exc:
                outcome.append(exc)

        thread = Thread(target=acquire, daemon=True)
        thread.start()
        self.assertTrue(authority.run_entered.wait(1.0))

        acquired = controller.lock.acquire(timeout=0.2)
        if acquired:
            controller.lock.release()
        authority.run_release.set()
        thread.join(3.0)

        self.assertTrue(
            acquired,
            "slow ResourceAuthority acquire held the global controller lock",
        )
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        if isinstance(outcome[0], BaseException):
            raise outcome[0]

    def test_same_run_creation_is_single_flight_and_refcounted(self) -> None:
        authority = _Authority()
        controller = _controller(authority)
        results = []
        errors = []

        def acquire(index: int) -> None:
            try:
                results.append(
                    controller._acquire_branch_scope_lease(
                        _context(f"lifetime-{index}"),
                        scope_unit(ScopeKind.BRANCH, f"branch-{index}"),
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [Thread(target=acquire, args=(i,), daemon=True) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3.0)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(authority.calls[ScopeKind.RUN.value], 1)
        self.assertEqual(authority.calls[ScopeKind.BRANCH.value], 2)
        self.assertEqual(controller._run_scope_refcounts["run-a"], 2)

        for guard, run_id in results:
            controller._release_branch_scope_guard(guard, run_id)

        self.assertNotIn("run-a", controller._run_scope_guards)
        self.assertNotIn("run-a", controller._run_scope_refcounts)
        self.assertEqual(len(authority.released), 3)


if __name__ == "__main__":
    unittest.main()
