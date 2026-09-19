from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    EnvironmentConcern,
    EnvironmentProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import CHATDEV_V1_AUDITED_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


class ChatDevV1EnvironmentAction(StrEnum):
    PREPARE_PHASE = "prepare_phase"
    APPLY_PHASE = "apply_phase"


class ChatDevV1PhaseDisposition(StrEnum):
    EXECUTE = "execute"
    SKIP = "skip"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class ChatDevV1EnvironmentPrepareRequest:
    phase_name: str
    cycle_index: int
    task_prompt: str
    prior_phase_results: tuple[JsonObject, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "phase_name",
            _text(self.phase_name, "ChatDev v1 environment phase_name"),
        )
        object.__setattr__(
            self,
            "task_prompt",
            _text(self.task_prompt, "ChatDev v1 environment task_prompt"),
        )
        if type(self.cycle_index) is not int or self.cycle_index < 0:
            raise ValueError(
                "ChatDev v1 environment cycle_index must be non-negative"
            )
        if type(self.prior_phase_results) is not tuple or any(
            not isinstance(row, Mapping) for row in self.prior_phase_results
        ):
            raise TypeError(
                "ChatDev v1 prior_phase_results must be an object tuple"
            )
        object.__setattr__(
            self,
            "prior_phase_results",
            tuple(freeze_json(row) for row in self.prior_phase_results),
        )


@dataclass(frozen=True, slots=True)
class ChatDevV1EnvironmentPreparation:
    phase_name: str
    cycle_index: int
    placeholders: JsonObject
    disposition: ChatDevV1PhaseDisposition = (
        ChatDevV1PhaseDisposition.EXECUTE
    )
    reason_code: str | None = None
    direct_conclusion: str | None = None
    environment_digest: str | None = None
    artifact_refs: tuple[str, ...] = ()
    provider_receipt: JsonValue = None
    preparation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "phase_name",
            _text(self.phase_name, "ChatDev v1 preparation phase_name"),
        )
        if type(self.cycle_index) is not int or self.cycle_index < 0:
            raise ValueError(
                "ChatDev v1 preparation cycle_index must be non-negative"
            )
        if not isinstance(self.placeholders, Mapping):
            raise TypeError(
                "ChatDev v1 preparation placeholders must be an object"
            )
        if not isinstance(self.disposition, ChatDevV1PhaseDisposition):
            raise TypeError(
                "ChatDev v1 preparation disposition is invalid"
            )
        if self.reason_code is not None:
            object.__setattr__(
                self,
                "reason_code",
                _text(self.reason_code, "ChatDev v1 reason_code"),
            )
        if self.direct_conclusion is not None and type(
            self.direct_conclusion
        ) is not str:
            raise TypeError(
                "ChatDev v1 direct_conclusion must be text or None"
            )
        if (
            self.disposition is ChatDevV1PhaseDisposition.DIRECT
            and self.direct_conclusion is None
        ):
            raise ValueError(
                "ChatDev v1 DIRECT preparation requires direct_conclusion"
            )
        if (
            self.disposition is not ChatDevV1PhaseDisposition.DIRECT
            and self.direct_conclusion is not None
        ):
            raise ValueError(
                "ChatDev v1 direct_conclusion is valid only for DIRECT"
            )
        if self.environment_digest is not None:
            object.__setattr__(
                self,
                "environment_digest",
                require_sha256(
                    self.environment_digest,
                    "ChatDev v1 environment_digest",
                ),
            )
        if type(self.artifact_refs) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.artifact_refs
        ):
            raise TypeError(
                "ChatDev v1 preparation artifact_refs must be a text tuple"
            )
        object.__setattr__(self, "placeholders", freeze_json(self.placeholders))
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "preparation_digest",
            canonical_digest({
                "phase_name": self.phase_name,
                "cycle_index": self.cycle_index,
                "placeholders": self.placeholders,
                "disposition": self.disposition.value,
                "reason_code": self.reason_code,
                "direct_conclusion": self.direct_conclusion,
                "environment_digest": self.environment_digest,
                "artifact_refs": self.artifact_refs,
                "provider_receipt": self.provider_receipt,
            }),
        )


@dataclass(frozen=True, slots=True)
class ChatDevV1EnvironmentApplyRequest:
    phase_name: str
    cycle_index: int
    conclusion: str
    phase_result: JsonObject
    preparation_result: JsonObject

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "phase_name",
            _text(self.phase_name, "ChatDev v1 apply phase_name"),
        )
        if type(self.cycle_index) is not int or self.cycle_index < 0:
            raise ValueError(
                "ChatDev v1 apply cycle_index must be non-negative"
            )
        if type(self.conclusion) is not str:
            raise TypeError("ChatDev v1 apply conclusion must be text")
        if not isinstance(self.phase_result, Mapping):
            raise TypeError("ChatDev v1 apply phase_result must be an object")
        if not isinstance(self.preparation_result, Mapping):
            raise TypeError(
                "ChatDev v1 apply preparation_result must be an object"
            )
        object.__setattr__(
            self,
            "phase_result",
            freeze_json(self.phase_result),
        )
        object.__setattr__(
            self,
            "preparation_result",
            freeze_json(self.preparation_result),
        )


@dataclass(frozen=True, slots=True)
class ChatDevV1EnvironmentApplication:
    phase_name: str
    cycle_index: int
    environment_digest: str
    state_projection: JsonObject = field(default_factory=dict)
    artifact_refs: tuple[str, ...] = ()
    provider_receipt: JsonValue = None
    application_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "phase_name",
            _text(self.phase_name, "ChatDev v1 application phase_name"),
        )
        if type(self.cycle_index) is not int or self.cycle_index < 0:
            raise ValueError(
                "ChatDev v1 application cycle_index must be non-negative"
            )
        object.__setattr__(
            self,
            "environment_digest",
            require_sha256(
                self.environment_digest,
                "ChatDev v1 application environment_digest",
            ),
        )
        if not isinstance(self.state_projection, Mapping):
            raise TypeError(
                "ChatDev v1 application state_projection must be an object"
            )
        if type(self.artifact_refs) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.artifact_refs
        ):
            raise TypeError(
                "ChatDev v1 application artifact_refs must be a text tuple"
            )
        object.__setattr__(
            self,
            "state_projection",
            freeze_json(self.state_projection),
        )
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "application_digest",
            canonical_digest({
                "phase_name": self.phase_name,
                "cycle_index": self.cycle_index,
                "environment_digest": self.environment_digest,
                "state_projection": self.state_projection,
                "artifact_refs": self.artifact_refs,
                "provider_receipt": self.provider_receipt,
            }),
        )


@runtime_checkable
class ChatDevV1SoftwareEnvironmentPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def prepare(
        self,
        request: ChatDevV1EnvironmentPrepareRequest,
    ) -> ChatDevV1EnvironmentPreparation: ...

    def apply(
        self,
        request: ChatDevV1EnvironmentApplyRequest,
    ) -> ChatDevV1EnvironmentApplication: ...


@dataclass(frozen=True, slots=True)
class ChatDevV1EnvironmentBinding:
    environment: ChatDevV1SoftwareEnvironmentPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.environment,
            ChatDevV1SoftwareEnvironmentPort,
        ):
            raise TypeError(
                "ChatDev v1 environment binding requires software environment port"
            )
        require_sha256(
            self.environment.identity_digest,
            "ChatDev v1 software environment identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "environment_identity_digest": (
                    self.environment.identity_digest
                ),
            }),
        )


def chatdev_v1_environment_initial_data(
    *,
    action: ChatDevV1EnvironmentAction,
    phase_name: str,
    cycle_index: int,
    task_prompt: str,
    prior_phase_results: tuple[JsonObject, ...] = (),
    conclusion: str | None = None,
    phase_result: JsonObject | None = None,
    preparation_result: JsonObject | None = None,
) -> JsonObject:
    if not isinstance(action, ChatDevV1EnvironmentAction):
        raise TypeError("ChatDev v1 environment action is invalid")
    phase_name = _text(phase_name, "ChatDev v1 environment phase_name")
    task_prompt = _text(task_prompt, "ChatDev v1 environment task_prompt")
    if type(cycle_index) is not int or cycle_index < 0:
        raise ValueError(
            "ChatDev v1 environment cycle_index must be non-negative"
        )
    if type(prior_phase_results) is not tuple or any(
        not isinstance(row, Mapping) for row in prior_phase_results
    ):
        raise TypeError(
            "ChatDev v1 prior_phase_results must be an object tuple"
        )
    if action is ChatDevV1EnvironmentAction.APPLY_PHASE:
        if type(conclusion) is not str:
            raise TypeError(
                "ChatDev v1 APPLY_PHASE requires text conclusion"
            )
        if not isinstance(phase_result, Mapping):
            raise TypeError(
                "ChatDev v1 APPLY_PHASE requires phase_result object"
            )
        if not isinstance(preparation_result, Mapping):
            raise TypeError(
                "ChatDev v1 APPLY_PHASE requires preparation_result object"
            )
    elif (
        conclusion is not None
        or phase_result is not None
        or preparation_result is not None
    ):
        raise ValueError(
            "ChatDev v1 PREPARE_PHASE cannot carry apply payload"
        )
    return {
        "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        "action": action.value,
        "phase_name": phase_name,
        "cycle_index": cycle_index,
        "task_prompt": task_prompt,
        "prior_phase_results": prior_phase_results,
        "conclusion": conclusion,
        "phase_result": {} if phase_result is None else phase_result,
        "preparation_result": (
            {} if preparation_result is None else preparation_result
        ),
        "result": None,
    }


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1EnvironmentBinding):
        raise TypeError(
            "ChatDev v1 environment dispatch requires environment binding"
        )
    action = ChatDevV1EnvironmentAction(
        _text(request.data.get("action"), "ChatDev v1 environment action")
    )
    return ProgramNodeResult(
        value={"action": action.value},
        next_node=(
            "prepare"
            if action is ChatDevV1EnvironmentAction.PREPARE_PHASE
            else "apply"
        ),
    )


def _prior_phase_results(value: object) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError(
            "ChatDev v1 prior_phase_results must be a sequence"
        )
    rows: list[JsonObject] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError(
                "ChatDev v1 prior_phase_results row must be an object"
            )
        rows.append(row)
    return tuple(rows)


def _prepare(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1EnvironmentBinding):
        raise TypeError(
            "ChatDev v1 environment prepare requires environment binding"
        )
    result = binding.environment.prepare(
        ChatDevV1EnvironmentPrepareRequest(
            phase_name=_text(
                request.data.get("phase_name"),
                "ChatDev v1 environment phase_name",
            ),
            cycle_index=int(request.data.get("cycle_index", 0)),
            task_prompt=_text(
                request.data.get("task_prompt"),
                "ChatDev v1 environment task_prompt",
            ),
            prior_phase_results=_prior_phase_results(
                request.data.get("prior_phase_results", ())
            ),
        )
    )
    if not isinstance(result, ChatDevV1EnvironmentPreparation):
        raise TypeError(
            "ChatDev v1 environment prepare must return preparation"
        )
    payload = {
        "phase_name": result.phase_name,
        "cycle_index": result.cycle_index,
        "placeholders": result.placeholders,
        "disposition": result.disposition.value,
        "reason_code": result.reason_code,
        "direct_conclusion": result.direct_conclusion,
        "environment_digest": result.environment_digest,
        "preparation_digest": result.preparation_digest,
        "artifact_refs": result.artifact_refs,
        "provider_receipt": result.provider_receipt,
    }
    return ProgramNodeResult(
        value=payload,
        state_update={"result": payload},
        status=MachineStatus.COMPLETED,
        artifact_refs=result.artifact_refs,
        events=({
            "type": "chatdev_v1_environment_prepared",
            "phase_name": result.phase_name,
            "cycle_index": result.cycle_index,
            "disposition": result.disposition.value,
            "preparation_digest": result.preparation_digest,
            "environment_digest": result.environment_digest,
        },),
    )


def _apply(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1EnvironmentBinding):
        raise TypeError(
            "ChatDev v1 environment apply requires environment binding"
        )
    phase_result = thaw_json(request.data.get("phase_result", {}))
    if not isinstance(phase_result, dict):
        raise TypeError("ChatDev v1 phase_result must be an object")
    preparation_result = thaw_json(
        request.data.get("preparation_result", {})
    )
    if not isinstance(preparation_result, dict):
        raise TypeError(
            "ChatDev v1 preparation_result must be an object"
        )
    result = binding.environment.apply(
        ChatDevV1EnvironmentApplyRequest(
            phase_name=_text(
                request.data.get("phase_name"),
                "ChatDev v1 environment phase_name",
            ),
            cycle_index=int(request.data.get("cycle_index", 0)),
            conclusion=str(request.data.get("conclusion", "")),
            phase_result=phase_result,
            preparation_result=preparation_result,
        )
    )
    if not isinstance(result, ChatDevV1EnvironmentApplication):
        raise TypeError(
            "ChatDev v1 environment apply must return application"
        )
    payload = {
        "phase_name": result.phase_name,
        "cycle_index": result.cycle_index,
        "environment_digest": result.environment_digest,
        "state_projection": result.state_projection,
        "application_digest": result.application_digest,
        "artifact_refs": result.artifact_refs,
        "provider_receipt": result.provider_receipt,
    }
    return ProgramNodeResult(
        value=payload,
        state_update={"result": payload},
        status=MachineStatus.COMPLETED,
        artifact_refs=result.artifact_refs,
        events=({
            "type": "chatdev_v1_environment_applied",
            "phase_name": result.phase_name,
            "cycle_index": result.cycle_index,
            "environment_digest": result.environment_digest,
            "application_digest": result.application_digest,
        },),
    )


def build_chatdev_v1_environment_program() -> ResearchProgram:
    return (
        EnvironmentProgramBuilder.create(
            program_id="chatdev.v1.software-environment",
            version=CHATDEV_V1_AUDITED_COMMIT[:12],
            state_schema="chatdev.v1.software-environment.state.v1",
            entrypoint="dispatch",
        )
        .semantic(
            "dispatch",
            EnvironmentConcern.QUERY,
            "chatdev.v1.environment.dispatch",
        )
        .semantic(
            "prepare",
            EnvironmentConcern.OBSERVATION,
            "chatdev.v1.environment.prepare",
        )
        .semantic(
            "apply",
            EnvironmentConcern.TRANSITION,
            "chatdev.v1.environment.apply",
        )
        .build()
    )


CHATDEV_V1_ENVIRONMENT_PROGRAM = (
    build_chatdev_v1_environment_program()
)


def chatdev_v1_environment_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "chatdev.v1.environment.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "chatdev.v1.environment.dispatch",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "chatdev.v1.environment.prepare",
            _prepare,
            canonical_digest({
                "operation": "chatdev.v1.environment.prepare",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "chatdev.v1.environment.apply",
            _apply,
            canonical_digest({
                "operation": "chatdev.v1.environment.apply",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def chatdev_v1_environment_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="chatdev.v1.software-environment",
        program=CHATDEV_V1_ENVIRONMENT_PROGRAM,
        operations=chatdev_v1_environment_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        },
    )


__all__ = [
    "CHATDEV_V1_ENVIRONMENT_PROGRAM",
    "ChatDevV1EnvironmentAction",
    "ChatDevV1EnvironmentApplication",
    "ChatDevV1EnvironmentApplyRequest",
    "ChatDevV1EnvironmentBinding",
    "ChatDevV1EnvironmentPreparation",
    "ChatDevV1EnvironmentPrepareRequest",
    "ChatDevV1PhaseDisposition",
    "ChatDevV1SoftwareEnvironmentPort",
    "build_chatdev_v1_environment_program",
    "chatdev_v1_environment_host",
    "chatdev_v1_environment_initial_data",
    "chatdev_v1_environment_operations",
]
