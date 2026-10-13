from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.policy.api import ExecutionBudgetPolicy
from noetrium_platform.research.execution.policy.runtime import SQLiteExecutionBudgetAuthority


class _Clock:
    def __init__(self) -> None:
        self.ns = 1_000_000_000

    def __call__(self) -> int:
        return self.ns

    def advance(self, seconds: float) -> None:
        self.ns += int(seconds * 1_000_000_000)


def test_scientific_wall_clock_starts_only_after_activation(tmp_path) -> None:
    clock = _Clock()
    authority = SQLiteExecutionBudgetAuthority(
        tmp_path / "budget.sqlite",
        resource_policy_digest="a" * 64,
        checkpoint_replay_proof_digest="b" * 64,
        clock_ns=clock,
    )
    policy = ExecutionBudgetPolicy(
        scope_id="assignment-ready-gate",
        budget_id="budget",
        budget_digest=canonical_digest({"budget": "ready-gate"}),
        replay_level="observational",
        max_seconds=30.0,
    )
    declared = authority.open_scope(policy)
    assert not declared.scientific_time_active
    assert declared.started_unix_ns == 0
    assert authority.remaining_seconds(policy.scope_id) == 30.0

    # Infrastructure admission / Minecraft startup must not consume science time.
    clock.advance(100.0)
    assert authority.remaining_seconds(policy.scope_id) == 30.0

    activated = authority.activate_scope(policy.scope_id)
    assert activated.scientific_time_active
    assert activated.started_unix_ns == clock.ns

    clock.advance(7.5)
    assert authority.remaining_seconds(policy.scope_id) == 22.5
    authority.require_active(policy.scope_id)
    authority.close()
