import math

import pytest

from noetrium_platform.research.execution.policy.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
)
from noetrium_platform.research.execution.policy.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.infrastructure.lifecycle.launch_control import RunLaunchIdentity
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority,
    SchedulingCandidate,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    UnifiedSchedulingAuthority,
)


def test_admission_budget_rejects_numeric_coercion():
    for value in (True, 1.5, "2"):
        with pytest.raises(TypeError):
            AdmissionBudget(max_total_in_flight=value)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            AdmissionBudget(max_total_in_flight=4, max_in_flight_per_group=value)  # type: ignore[arg-type]


def test_admission_identity_and_intent_are_strict_and_canonical():
    identity = AdmissionIdentity(tenant_id=" tenant ", resource_id=" resource ")
    assert identity.tenant_id == "tenant"
    assert identity.resource_id == "resource"
    for value in (42, True):
        with pytest.raises(TypeError):
            AdmissionIdentity(tenant_id=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AdmissionIdentity(resource_id="   ")
    with pytest.raises(TypeError):
        AdmissionIntent(priority="high")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AdmissionIntent(mode="reject")  # type: ignore[arg-type]
    immediate = AdmissionIntent(ExecutionPriority.HIGH, 0.0)
    assert immediate.reject_if_wait_required is True


def test_admission_group_identity_never_coerces_objects_to_text():
    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=2),
        scheduling_authority=UnifiedSchedulingAuthority(),
    )
    with pytest.raises(TypeError):
        authority.register_group(7, identity=AdmissionIdentity())  # type: ignore[arg-type]
    authority.register_group(" group ", identity=AdmissionIdentity())
    assert authority.snapshot().groups[0].group_id == "group"


def test_scheduling_candidate_and_policy_reject_permissive_numeric_inputs():
    with pytest.raises(TypeError):
        SchedulingCandidate(True, "group", ExecutionPriority.NORMAL, 1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        SchedulingCandidate(1, "group", "normal", 1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SchedulingCandidate(1, "group", ExecutionPriority.NORMAL, math.inf)
    with pytest.raises(TypeError):
        SchedulingCandidate(
            1,
            "group",
            ExecutionPriority.NORMAL,
            1.0,
            estimated_service_seconds=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        SchedulingCandidate(
            1,
            "group",
            ExecutionPriority.NORMAL,
            1.0,
            estimated_service_seconds=math.inf,
        )
    candidate = SchedulingCandidate(1, " group ", ExecutionPriority.NORMAL, 1)
    assert candidate.group_id == "group"
    assert candidate.enqueued_monotonic == 1.0
    policy = UnifiedSchedulingAuthority()
    with pytest.raises(TypeError):
        policy.select((candidate,), now_monotonic=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        policy.select((candidate,), now_monotonic=math.nan)


def _record_service(
    authority: UnifiedSchedulingAuthority,
    *,
    tenant_id: str,
    flow_id: str,
    service_quanta: int,
) -> None:
    authority.record_grant(tenant_id=tenant_id, flow_id=flow_id)
    authority.record_completion(
        tenant_id=tenant_id,
        flow_id=flow_id,
        service_quanta=service_quanta,
    )


def test_fair_priority_scheduling_is_tenant_fair_before_flow_fair() -> None:
    authority = UnifiedSchedulingAuthority()
    # A and B are simultaneously backlogged. A receives more service while
    # both are active, so B owns the fair-service debt. Sequential idle periods
    # intentionally do not accumulate credit (VTC counter-lifting semantics).
    authority.record_grant(tenant_id="paper-a", flow_id="history-a")
    authority.record_grant(tenant_id="paper-b", flow_id="history-b")
    authority.record_completion(
        tenant_id="paper-a",
        flow_id="history-a",
        service_quanta=50,
    )
    authority.record_completion(
        tenant_id="paper-b",
        flow_id="history-b",
        service_quanta=10,
    )
    candidates = tuple(
        SchedulingCandidate(
            index,
            f"group-a-{index}",
            ExecutionPriority.NORMAL,
            99.0,
            tenant_id="paper-a",
        )
        for index in range(100)
    ) + (
        SchedulingCandidate(
            100,
            "group-b-0",
            ExecutionPriority.NORMAL,
            99.0,
            tenant_id="paper-b",
        ),
    )
    assert authority.select(candidates, now_monotonic=100.0) == 100

    # Within one tenant, the flow with less consumed service wins.
    flow_authority = UnifiedSchedulingAuthority()
    _record_service(
        flow_authority,
        tenant_id="paper-a",
        flow_id="group-a-0",
        service_quanta=20,
    )
    _record_service(
        flow_authority,
        tenant_id="paper-a",
        flow_id="group-a-1",
        service_quanta=3,
    )
    assert flow_authority.select(
        candidates[:2],
        now_monotonic=100.0,
    ) == 1


def test_fair_priority_scheduling_prefers_lower_active_tenant_share() -> None:
    authority = UnifiedSchedulingAuthority()
    # Four active permits owned by A make B the lower active-share tenant.
    authority.record_grant(
        tenant_id="paper-a",
        flow_id="group-a",
        permit_count=4,
    )
    candidates = (
        SchedulingCandidate(
            1,
            "group-a",
            ExecutionPriority.NORMAL,
            99.0,
            tenant_id="paper-a",
        ),
        SchedulingCandidate(
            2,
            "group-b",
            ExecutionPriority.NORMAL,
            99.0,
            tenant_id="paper-b",
        ),
    )
    assert authority.select(candidates, now_monotonic=100.0) == 2



def test_run_launch_identity_canonicalizes_sha256_and_rejects_non_text():
    digest = "A" * 64
    identity = RunLaunchIdentity(f"  {digest}  ")
    assert identity.digest() == "a" * 64
    with pytest.raises(TypeError):
        RunLaunchIdentity(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RunLaunchIdentity("not-a-digest")


def test_decision_cycle_identity_is_canonical_and_random_ids_keep_full_entropy():
    from noetrium_platform.research.execution.decision.cycle_identity import (
        DecisionCycleIdentity,
        RandomDecisionCycleIdentityProvider,
    )

    identity = DecisionCycleIdentity(" run ", " dc ", " session ", " task ", " trace ")
    assert (identity.run_id, identity.decision_cycle_id, identity.session_id) == ("run", "dc", "session")
    with pytest.raises(TypeError):
        DecisionCycleIdentity(1, "dc", "session", "task", "trace")  # type: ignore[arg-type]

    allocated = RandomDecisionCycleIdentityProvider().allocate()
    assert allocated.run_id.startswith("run_") and len(allocated.run_id.removeprefix("run_")) == 32
    assert allocated.decision_cycle_id.startswith("dc_") and len(allocated.decision_cycle_id.removeprefix("dc_")) == 32
    assert allocated.session_id.startswith("session_") and len(allocated.session_id.removeprefix("session_")) == 32


def test_rate_aware_backlog_tie_break_and_fairness() -> None:
    authority = UnifiedSchedulingAuthority()
    known = SchedulingCandidate(
        1,
        "known",
        ExecutionPriority.NORMAL,
        99.0,
        tenant_id="paper",
        waiting_permits=8,
        observed_service_rate_per_second=4.0,
    )
    slow = SchedulingCandidate(
        2,
        "slow",
        ExecutionPriority.NORMAL,
        99.0,
        tenant_id="paper",
        waiting_permits=2,
        observed_service_rate_per_second=1.0,
    )
    assert authority.select((slow, known), now_monotonic=100.0) == 1

    unknown = SchedulingCandidate(
        3,
        "unknown",
        ExecutionPriority.NORMAL,
        99.0,
        tenant_id="paper",
    )
    assert authority.select((known, unknown), now_monotonic=100.0) == 3

    # Global service debt outranks throughput: a less-served tenant gets the
    # next turn even if its measured service rate is lower.
    _record_service(
        authority,
        tenant_id="paper",
        flow_id="paper-history",
        service_quanta=100,
    )
    _record_service(
        authority,
        tenant_id="paper-b",
        flow_id="paper-b-history",
        service_quanta=1,
    )
    other_tenant = SchedulingCandidate(
        4,
        "other",
        ExecutionPriority.NORMAL,
        99.0,
        tenant_id="paper-b",
        waiting_permits=1,
        observed_service_rate_per_second=0.01,
    )
    assert authority.select((known, other_tenant), now_monotonic=100.0) == 4
