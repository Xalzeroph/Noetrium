from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetDelta,
    ExecutionBudgetPolicy,
)
from noetrium_platform.research.execution.policy.runtime import (
    SQLiteExecutionBudgetAuthority,
)


class _Clock:
    def __init__(self) -> None:
        self.ns = 1_000_000_000

    def __call__(self) -> int:
        return self.ns

    def advance(self, seconds: float) -> None:
        self.ns += int(seconds * 1_000_000_000)


class ExecutionBudgetActiveScopeCacheTests(unittest.TestCase):
    def test_full_scope_lifecycle_after_active_row_cache_optimization(self) -> None:
        with TemporaryDirectory() as directory:
            clock = _Clock()
            authority = SQLiteExecutionBudgetAuthority(
                Path(directory) / "budget.sqlite",
                resource_policy_digest="a" * 64,
                checkpoint_replay_proof_digest="b" * 64,
                clock_ns=clock,
            )
            policy = ExecutionBudgetPolicy(
                scope_id="scope-a",
                budget_id="budget-a",
                budget_digest=canonical_digest({"budget": "scope-a"}),
                replay_level="observational",
                max_steps=20,
                max_seconds=120.0,
                max_tokens=10_000,
            )

            declared = authority.open_scope(policy)
            self.assertFalse(declared.scientific_time_active)
            self.assertNotIn(policy.scope_id, authority._active_scope_rows)

            activated = authority.activate_scope(policy.scope_id)
            self.assertTrue(activated.scientific_time_active)
            self.assertIn(policy.scope_id, authority._active_scope_rows)

            first_snapshot = authority.snapshot(policy.scope_id)
            second_snapshot = authority.snapshot(policy.scope_id)
            self.assertEqual(first_snapshot.policy_digest, policy.policy_digest)
            self.assertEqual(first_snapshot, second_snapshot)

            requested = ExecutionBudgetDelta(
                steps=2,
                model_calls=1,
                tokens=100,
                working_seconds=1.5,
            )
            committed = ExecutionBudgetDelta(
                steps=2,
                model_calls=1,
                tokens=80,
                working_seconds=1.25,
            )
            reservation = authority.reserve(
                policy.scope_id,
                "charge-commit",
                requested,
            )
            snapshot, violations = authority.commit(reservation, committed)
            self.assertEqual(violations, ())
            self.assertEqual(snapshot.usage.steps, 2)
            self.assertEqual(snapshot.usage.tokens, 80)
            self.assertEqual(snapshot.reserved.steps, 0)

            abort_reservation = authority.reserve(
                policy.scope_id,
                "charge-abort",
                ExecutionBudgetDelta(steps=1, tokens=10),
            )
            aborted = authority.abort(abort_reservation)
            self.assertEqual(aborted.usage.steps, 2)
            self.assertEqual(aborted.reserved.steps, 0)

            clock.advance(5.0)
            remaining = authority.remaining_seconds(policy.scope_id)
            self.assertIsNotNone(remaining)
            self.assertAlmostEqual(float(remaining), 115.0)
            authority.require_active(policy.scope_id)
            authority.close()


if __name__ == "__main__":
    unittest.main()
