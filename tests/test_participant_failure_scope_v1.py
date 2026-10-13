"""Participant Method failures are evidence, not whole-paper failure scopes."""
from noetrium_platform.composition.participant_workload import (
    _participant_method_failure_scope,
)
from noetrium_platform.research.execution.workflow.api import MethodRunStatus


def test_agent_method_failure_is_an_episode_result_not_a_failed_study():
    assert _participant_method_failure_scope(
        (MethodRunStatus.SUCCEEDED.value, MethodRunStatus.FAILED.value)
    ) == "task"
    assert _participant_method_failure_scope(
        (MethodRunStatus.LIMIT_REACHED.value,)
    ) == "task"


def test_interrupted_participant_propagates_lifecycle_control():
    assert _participant_method_failure_scope(
        (MethodRunStatus.SUCCEEDED.value, MethodRunStatus.INTERRUPTED.value)
    ) == "branch"
