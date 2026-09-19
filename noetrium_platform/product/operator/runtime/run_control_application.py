from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib
from typing import TYPE_CHECKING, Any, cast

from noetrium_platform.research.execution.decision.cycle_identity import (
    DecisionCycleIdentity,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.product.operator.api import (
    ResearchAction,
    ResearchOperationFailure,
    ResearchRequest,
    ResearchResult,
)

if TYPE_CHECKING:
    from noetrium_platform.research.experimentation.run.control.api import (
        RunControlPort,
    )

_HEX = frozenset("0123456789abcdef")
_STATE_CHANGING = frozenset({
    ResearchAction.RUN,
    ResearchAction.STOP,
    ResearchAction.RESUME,
    ResearchAction.RECONCILE,
})
_FAILURE_STATES = frozenset({"failed", "recovery_required"})


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_sha256(value: object, field: str) -> str:
    text = _require_text(value, field)
    if len(text) != 64 or any(character not in _HEX for character in text):
        raise ValueError(f"{field} must be a canonical lowercase SHA-256")
    return text


def _require_revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(
            "run control expected_revision must be a positive integer"
        )
    return value


def _payload_mapping(request: ResearchRequest) -> Mapping[str, JsonValue]:
    payload = request.payload
    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("run control payload must be a JSON object")
    return cast(Mapping[str, JsonValue], payload)


def _require_fields(
    payload: Mapping[str, JsonValue],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
) -> None:
    fields = frozenset(payload)
    extra = fields - allowed
    missing = required - fields
    if extra:
        raise ValueError(
            f"run control payload has unexpected fields: {sorted(extra)}"
        )
    if missing:
        raise ValueError(
            f"run control payload is missing required fields: {sorted(missing)}"
        )


def _restore_cycle(value: object) -> DecisionCycleIdentity:
    if not isinstance(value, Mapping):
        raise TypeError("restore_cycle_identity must be a JSON object")
    expected = frozenset({
        "run_id",
        "decision_cycle_id",
        "session_id",
        "task_id",
        "trace_id",
    })
    if frozenset(value) != expected:
        raise ValueError("restore_cycle_identity fields must be exact")
    return DecisionCycleIdentity(
        **{field: value[field] for field in expected}
    )


def _load_run_control_contracts() -> Any:
    try:
        return importlib.import_module(
            "noetrium_platform.research.experimentation.run.control.api"
        )
    except ImportError as exc:
        raise ValueError(
            "run-control contract is unavailable in this source cut"
        ) from exc


@dataclass(frozen=True, slots=True)
class RunControlResearchBinding:
    control: "RunControlPort"
    run_id: str
    run_manifest_digest: str

    def __post_init__(self) -> None:
        if not callable(getattr(self.control, "execute", None)):
            raise TypeError(
                "run control binding requires an execute(request) port"
            )
        object.__setattr__(
            self,
            "run_id",
            _require_text(self.run_id, "run control run_id"),
        )
        object.__setattr__(
            self,
            "run_manifest_digest",
            _require_sha256(
                self.run_manifest_digest,
                "run control manifest digest",
            ),
        )


def _run_control_request(
    binding: RunControlResearchBinding,
    request: ResearchRequest,
):
    contracts = _load_run_control_contracts()
    if request.target != binding.run_id:
        raise ValueError(
            "research target does not match bound run identity"
        )
    payload = _payload_mapping(request)
    if request.action in {ResearchAction.INSPECT, ResearchAction.EVIDENCE}:
        _require_fields(
            payload,
            allowed=frozenset({"expected_revision"}),
            required=frozenset(),
        )
        revision = (
            None
            if "expected_revision" not in payload
            else _require_revision(payload["expected_revision"])
        )
        restore_checkpoint_id = None
        restore_cycle = None
    elif request.action is ResearchAction.RESUME:
        _require_fields(
            payload,
            allowed=frozenset({
                "expected_revision",
                "restore_checkpoint_id",
                "restore_cycle_identity",
            }),
            required=frozenset({
                "expected_revision",
                "restore_checkpoint_id",
                "restore_cycle_identity",
            }),
        )
        revision = _require_revision(payload["expected_revision"])
        restore_checkpoint_id = _require_text(
            payload["restore_checkpoint_id"],
            "restore_checkpoint_id",
        )
        restore_cycle = _restore_cycle(
            payload["restore_cycle_identity"]
        )
    else:
        _require_fields(
            payload,
            allowed=frozenset({"expected_revision"}),
            required=frozenset({"expected_revision"}),
        )
        revision = _require_revision(payload["expected_revision"])
        restore_checkpoint_id = None
        restore_cycle = None

    target = contracts.RunControlTarget(
        binding.run_id,
        binding.run_manifest_digest,
        revision,
    )
    return contracts.RunControlRequest(
        contracts.RunControlAction(request.action.value),
        target,
        restore_checkpoint_id=restore_checkpoint_id,
        restore_cycle_identity=restore_cycle,
    )


def _machine_cut_payload(cut) -> dict[str, object]:
    return {
        "machine_id": cut.machine_id,
        "revision": cut.revision,
        "commit_id": cut.commit_id,
        "state_digest": cut.state_digest,
        "program_digest": cut.program_digest,
        "cut_digest": cut.cut_digest,
    }


def _pending_payload(pending) -> dict[str, object] | None:
    if pending is None:
        return None
    return {
        "operation_id": pending.operation_id,
        "action": pending.action.value,
        "base_revision": pending.base_revision,
        "base_phase": pending.base_phase.value,
        "base_latest_checkpoint_id": pending.base_latest_checkpoint_id,
        "base_checkpoint_manifest_digest": (
            pending.base_checkpoint_manifest_digest
        ),
        "restore_checkpoint_id": pending.restore_checkpoint_id,
        "restore_checkpoint_manifest_digest": (
            pending.restore_checkpoint_manifest_digest
        ),
        "restore_cycle_identity_digest": (
            pending.restore_cycle_identity_digest
        ),
        "prepared_digest": pending.digest,
    }


def _evidence_payload(receipt) -> dict[str, object] | None:
    evidence = receipt.evidence_bundle_receipt
    if evidence is None:
        return None
    artifact = evidence.manifest_artifact_receipt
    return {
        "bundle_id": evidence.bundle_id,
        "run_id": evidence.run_id,
        "run_manifest_digest": evidence.run_manifest_digest,
        "manifest_ref": evidence.manifest_ref,
        "manifest_sha256": evidence.manifest_sha256,
        "manifest_artifact": {
            "artifact_ref": artifact.artifact_ref,
            "artifact_kind": artifact.artifact_kind.value,
            "generation": artifact.generation,
            "content_sha256": artifact.content_sha256,
            "byte_size": artifact.byte_size,
            "record_count": artifact.record_count,
        },
    }


def _research_result(
    binding: RunControlResearchBinding,
    request: ResearchRequest,
    receipt,
) -> ResearchResult:
    contracts = _load_run_control_contracts()
    if type(receipt) is not contracts.RunControlReceipt:
        raise TypeError(
            "run control port returned a non-RunControlReceipt"
        )
    if receipt.action.value != request.action.value:
        raise ValueError(
            "run control receipt action does not match research request"
        )
    if receipt.run_id != binding.run_id or receipt.run_id != request.target:
        raise ValueError("run control receipt run identity drifted")
    if receipt.run_manifest_digest != binding.run_manifest_digest:
        raise ValueError("run control receipt manifest digest drifted")
    if receipt.machine_cut.machine_id != f"research-run:{binding.run_id}":
        raise ValueError("run control MachineCut identity drifted")

    evidence = receipt.evidence_bundle_receipt
    if evidence is not None and (
        evidence.run_id != binding.run_id
        or evidence.run_manifest_digest != binding.run_manifest_digest
    ):
        raise ValueError("run control evidence identity drifted")

    payload = {
        "run_identity_digest": receipt.run_identity_digest,
        "run_manifest_digest": receipt.run_manifest_digest,
        "control_revision": receipt.control_revision,
        "machine_cut": _machine_cut_payload(receipt.machine_cut),
        "latest_checkpoint_id": receipt.latest_checkpoint_id,
        "checkpoint_manifest_digest": receipt.checkpoint_manifest_digest,
        "pending_operation": _pending_payload(receipt.pending_operation),
        "evidence_bundle": _evidence_payload(receipt),
        "outcomes": {
            "execution": receipt.outcomes.execution.value,
            "task": receipt.outcomes.task.value,
            "evidence": receipt.outcomes.evidence.value,
            "scientific": receipt.outcomes.scientific.value,
        },
    }
    return ResearchResult(
        request.action,
        request.target,
        receipt.phase.value,
        payload,
    )


class RunControlResearchApplication:
    """Translate product requests onto Machine-backed run control."""

    def __init__(self, binding: RunControlResearchBinding) -> None:
        if type(binding) is not RunControlResearchBinding:
            raise TypeError(
                "run-control research application requires typed binding"
            )
        self._binding = binding

    def execute(self, request: ResearchRequest) -> ResearchResult:
        if type(request) is not ResearchRequest:
            raise TypeError(
                "run-control research application requires ResearchRequest"
            )
        contracts = _load_run_control_contracts()
        control_request = _run_control_request(self._binding, request)
        try:
            receipt = self._binding.control.execute(control_request)
        except contracts.RunControlActionFailure as exc:
            result = _research_result(
                self._binding,
                request,
                exc.receipt,
            )
            raise ResearchOperationFailure(result) from exc
        except contracts.RunControlError as exc:
            raise ValueError(
                f"run control rejected {request.action.value}: "
                f"{type(exc).__name__}"
            ) from exc
        result = _research_result(self._binding, request, receipt)
        if (
            request.action in _STATE_CHANGING
            and result.state in _FAILURE_STATES
        ):
            raise ResearchOperationFailure(result)
        return result


def bind_run_control_application(
    control: "RunControlPort",
    *,
    run_id: str,
    run_manifest_digest: str,
) -> RunControlResearchApplication:
    return RunControlResearchApplication(
        RunControlResearchBinding(
            control,
            run_id,
            run_manifest_digest,
        )
    )


__all__ = [
    "RunControlResearchApplication",
    "RunControlResearchBinding",
    "bind_run_control_application",
]
