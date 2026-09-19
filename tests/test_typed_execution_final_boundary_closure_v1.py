import math

import pytest

from noetrium_platform.research.execution.admission.api import (
    AdmissionBudget,
    AdmissionIdentity,
    AdmissionIntent,
    AdmissionMode,
)
from noetrium_platform.research.execution.admission.runtime import HierarchicalAdmissionAuthority
from noetrium_platform.infrastructure.lifecycle.launch_control import RunLaunchIdentity
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority, SchedulingCandidate
from noetrium_platform.research.execution.scheduling.runtime import FairPrioritySchedulingPolicy


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
    assert AdmissionIntent(ExecutionPriority.HIGH, AdmissionMode.REJECT).mode is AdmissionMode.REJECT


def test_admission_group_identity_never_coerces_objects_to_text():
    authority = HierarchicalAdmissionAuthority(
        budget=AdmissionBudget(max_total_in_flight=2),
        scheduling=FairPrioritySchedulingPolicy(),
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
        FairPrioritySchedulingPolicy(priority_aging_seconds=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        FairPrioritySchedulingPolicy(priority_aging_seconds=math.inf)
    candidate = SchedulingCandidate(1, " group ", ExecutionPriority.NORMAL, 1)
    assert candidate.group_id == "group"
    assert candidate.enqueued_monotonic == 1.0
    policy = FairPrioritySchedulingPolicy(priority_aging_seconds=1)
    with pytest.raises(TypeError):
        policy.select((candidate,), group_last_grant={}, now_monotonic=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        policy.select((candidate,), group_last_grant={}, now_monotonic=math.nan)


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
