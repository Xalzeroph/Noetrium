from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.foundation.kernel.kernel import MachineCut
from noetrium_platform.product.operator.api import (
    ResearchAction,
    ResearchOperationFailure,
    ResearchRequest,
)
from noetrium_platform.product.operator.runtime.run_control_application import (
    bind_run_control_application,
)
from noetrium_platform.research.experimentation.run.control.api import (
    RunControlActionFailure,
    RunControlPhase,
    RunControlReceipt,
    RunEvidenceValidity,
    RunExecutionOutcome,
    RunOutcomeProjection,
    RunScientificValidity,
    RunTaskOutcome,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


_EXECUTION = {
    RunControlPhase.CREATED: RunExecutionOutcome.NOT_STARTED,
    RunControlPhase.RUNNING: RunExecutionOutcome.IN_PROGRESS,
    RunControlPhase.STOPPED: RunExecutionOutcome.STOPPED,
    RunControlPhase.RECOVERY_REQUIRED: RunExecutionOutcome.RECOVERY_REQUIRED,
    RunControlPhase.COMPLETED: RunExecutionOutcome.SUCCEEDED,
    RunControlPhase.FAILED: RunExecutionOutcome.FAILED,
    RunControlPhase.CLOSED: RunExecutionOutcome.CLOSED,
}


def _receipt(request, *, phase: RunControlPhase = RunControlPhase.RUNNING):
    revision = request.target.expected_revision or 3
    return RunControlReceipt(
        action=request.action,
        run_id=request.target.run_id,
        run_identity_digest=_sha("identity"),
        run_manifest_digest=request.target.run_manifest_digest,
        phase=phase,
        machine_cut=MachineCut(
            f"research-run:{request.target.run_id}",
            revision,
            _sha(f"commit:{revision}"),
            _sha(f"state:{phase.value}:{revision}"),
            _sha("program"),
        ),
        latest_checkpoint_id=None,
        checkpoint_manifest_digest=None,
        pending_operation=None,
        evidence_bundle_receipt=None,
        outcomes=RunOutcomeProjection(
            _EXECUTION[phase],
            RunTaskOutcome.NOT_EVALUATED,
            (
                RunEvidenceValidity.NOT_FINALIZED
                if request.action.value == "evidence"
                else RunEvidenceValidity.NOT_OBSERVED
            ),
            RunScientificValidity.NOT_EVALUATED,
        ),
    )


class _Control:
    def __init__(
        self,
        *,
        phase: RunControlPhase = RunControlPhase.RUNNING,
        fail: bool = False,
    ) -> None:
        self.phase = phase
        self.fail = fail
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        receipt = _receipt(request, phase=self.phase)
        if self.fail:
            raise RunControlActionFailure(receipt)
        return receipt


def _application(control=None):
    control = control or _Control()
    return (
        bind_run_control_application(
            control,
            run_id="run-1",
            run_manifest_digest="a" * 64,
        ),
        control,
    )


def _cycle_payload() -> dict[str, str]:
    return {
        "run_id": "run-1",
        "decision_cycle_id": "cycle-1",
        "session_id": "session-1",
        "task_id": "task-1",
        "trace_id": "trace-1",
    }


@pytest.mark.parametrize(
    ("action", "payload", "revision"),
    [
        (ResearchAction.RUN, {"expected_revision": 1}, 1),
        (ResearchAction.INSPECT, None, None),
        (ResearchAction.STOP, {"expected_revision": 3}, 3),
        (ResearchAction.RECONCILE, {"expected_revision": 4}, 4),
        (ResearchAction.EVIDENCE, {"expected_revision": 4}, 4),
    ],
)
def test_adapter_translates_product_actions_to_machine_revision_fence(
    action,
    payload,
    revision,
):
    application, control = _application()
    result = application.execute(
        ResearchRequest(action, "run-1", payload)
    )
    (translated,) = control.requests
    assert translated.action.value == action.value
    assert translated.target.run_id == "run-1"
    assert translated.target.run_manifest_digest == "a" * 64
    assert translated.target.expected_revision == revision
    assert result.payload["run_manifest_digest"] == "a" * 64
    assert result.payload["machine_cut"]["machine_id"] == "research-run:run-1"
    assert result.payload["control_revision"] == result.payload["machine_cut"]["revision"]


def test_resume_preserves_exact_restore_identity() -> None:
    application, control = _application()
    result = application.execute(
        ResearchRequest(
            ResearchAction.RESUME,
            "run-1",
            {
                "expected_revision": 5,
                "restore_checkpoint_id": "checkpoint-4",
                "restore_cycle_identity": _cycle_payload(),
            },
        )
    )
    (translated,) = control.requests
    assert translated.target.expected_revision == 5
    assert translated.restore_checkpoint_id == "checkpoint-4"
    assert translated.restore_cycle_identity.run_id == "run-1"
    assert result.state == "running"


@pytest.mark.parametrize(
    "research_request",
    [
        ResearchRequest(ResearchAction.RUN, "run-1", None),
        ResearchRequest(
            ResearchAction.RUN,
            "run-1",
            {"expected_revision": True},
        ),
        ResearchRequest(
            ResearchAction.STOP,
            "run-1",
            {"expected_revision": 1, "extra": 1},
        ),
        ResearchRequest(
            ResearchAction.RESUME,
            "run-1",
            {"expected_revision": 1},
        ),
        ResearchRequest(
            ResearchAction.INSPECT,
            "run-1",
            {"unexpected": 1},
        ),
    ],
)
def test_adapter_rejects_unfenced_or_non_exact_payloads(
    research_request,
) -> None:
    application, _control = _application()
    with pytest.raises((TypeError, ValueError)):
        application.execute(research_request)


def test_adapter_rejects_target_identity_drift() -> None:
    application, _control = _application()
    with pytest.raises(ValueError, match="bound run identity"):
        application.execute(
            ResearchRequest(
                ResearchAction.INSPECT,
                "other-run",
            )
        )


def test_state_change_recovery_required_surfaces_authoritative_failure() -> None:
    application, _control = _application(
        _Control(phase=RunControlPhase.RECOVERY_REQUIRED)
    )
    with pytest.raises(ResearchOperationFailure) as captured:
        application.execute(
            ResearchRequest(
                ResearchAction.RECONCILE,
                "run-1",
                {"expected_revision": 3},
            )
        )
    assert captured.value.result.state == "recovery_required"
    assert captured.value.result.payload["machine_cut"]["revision"] == 3


def test_action_failure_preserves_machine_cut() -> None:
    application, _control = _application(
        _Control(
            phase=RunControlPhase.RECOVERY_REQUIRED,
            fail=True,
        )
    )
    with pytest.raises(ResearchOperationFailure) as captured:
        application.execute(
            ResearchRequest(
                ResearchAction.RUN,
                "run-1",
                {"expected_revision": 2},
            )
        )
    result = captured.value.result
    assert result.state == "recovery_required"
    assert result.payload["control_revision"] == 2
    assert result.payload["machine_cut"]["revision"] == 2


def test_read_only_inspect_can_report_failed_without_manufacturing_failure() -> None:
    application, _control = _application(
        _Control(phase=RunControlPhase.FAILED)
    )
    result = application.execute(
        ResearchRequest(ResearchAction.INSPECT, "run-1")
    )
    assert result.state == "failed"


def test_adapter_rejects_non_typed_receipt() -> None:
    class _BadControl:
        def execute(self, request):
            del request
            return object()

    application, _control = _application(_BadControl())
    with pytest.raises(TypeError, match="non-RunControlReceipt"):
        application.execute(
            ResearchRequest(ResearchAction.INSPECT, "run-1")
        )


def test_machine_cut_identity_drift_is_rejected() -> None:
    class _BadCutControl:
        def execute(self, request):
            receipt = _receipt(request)
            return RunControlReceipt(
                receipt.action,
                receipt.run_id,
                receipt.run_identity_digest,
                receipt.run_manifest_digest,
                receipt.phase,
                MachineCut(
                    "research-run:other-run",
                    receipt.machine_cut.revision,
                    receipt.machine_cut.commit_id,
                    receipt.machine_cut.state_digest,
                    receipt.machine_cut.program_digest,
                ),
                receipt.latest_checkpoint_id,
                receipt.checkpoint_manifest_digest,
                receipt.pending_operation,
                receipt.evidence_bundle_receipt,
                receipt.outcomes,
            )

    application, _control = _application(_BadCutControl())
    with pytest.raises(ValueError):
        application.execute(
            ResearchRequest(ResearchAction.INSPECT, "run-1")
        )
