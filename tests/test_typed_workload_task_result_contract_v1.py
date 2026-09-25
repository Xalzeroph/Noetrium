from dataclasses import replace
import math

import pytest

from noetrium_platform.research.experimentation.workload.api import (
    WorkloadEvaluation,
    WorkloadMethodReceipt,
    WorkloadTaskResult,
)


def _method_receipt() -> WorkloadMethodReceipt:
    return WorkloadMethodReceipt(
        "run-1", "a" * 64, "b" * 64, "succeeded", 2, "complete"
    )


def _result() -> WorkloadTaskResult:
    return WorkloadTaskResult(
        task_id="task-1", family="family", success=True, utility=1.0,
        steps=2, duration_s=0.25, lineage_id="lineage-1",
        method_receipt=_method_receipt(), diagnostics={"trace": {"ok": True}},
    )


@pytest.mark.parametrize(("field", "value"), [
    ("success", 1), ("blocked", 0), ("steps", True),
    ("utility", math.nan), ("duration_s", math.inf), ("duration_s", -0.1),
    ("failure_scope", "unknown"),
])
def test_workload_task_result_rejects_invalid_typed_state(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(_result(), **{field: value})


def test_workload_task_result_rejects_impossible_outcome_combinations():
    with pytest.raises(ValueError): replace(_result(), blocked=True)
    with pytest.raises(ValueError): replace(_result(), failure_reason="unexpected")
    with pytest.raises(ValueError): replace(_result(), success=False)
    failed = replace(_result(), success=False, failure_reason="task_failed")
    blocked = replace(_result(), success=False, blocked=True, failure_reason="blocked_dependency")
    assert not failed.success and not failed.blocked
    assert not blocked.success and blocked.blocked


def test_workload_method_receipt_requires_exact_digest_and_step_types():
    with pytest.raises(ValueError, match="program_digest"):
        replace(_method_receipt(), program_digest="short")
    with pytest.raises(ValueError, match="run_digest"):
        replace(_method_receipt(), run_digest="g" * 64)
    with pytest.raises(ValueError, match="step_count"):
        replace(_method_receipt(), step_count=-1)


def test_workload_task_result_deep_freezes_diagnostics():
    diagnostics = {"trace": {"path": [1, 2], "ok": True}}
    result = replace(_result(), diagnostics=diagnostics)
    diagnostics["trace"]["path"].append(3)
    diagnostics["trace"]["ok"] = False
    assert tuple(result.diagnostics["trace"]["path"]) == (1, 2)
    assert result.diagnostics["trace"]["ok"] is True
    with pytest.raises(TypeError): result.diagnostics["new"] = 1


def test_workload_evaluation_owns_domain_success_not_method_provenance():
    evaluation = WorkloadEvaluation(True, 0.5, diagnostics={"score": 0.5})
    assert evaluation.success is True
    assert evaluation.utility == 0.5
    with pytest.raises(ValueError): WorkloadEvaluation(False, 0.0)
    with pytest.raises(ValueError): WorkloadEvaluation(True, 1.0, failure_reason="bad")
