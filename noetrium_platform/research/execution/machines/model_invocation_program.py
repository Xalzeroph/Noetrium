"""Programmable model-invocation semantics executed by RuntimeMachine.

Model identity, qualification, request construction, endpoint routing and raw
provider I/O remain owned by the model subsystem. This module owns only
paper-variable invocation semantics: admitted member order, fallback/fanout,
failure continuation and response selection.

Each provider attempt is one Machine transition. Large responses are persisted
through the injected ArtifactBlobStorePort; Machine state stores only exact
content references and digests, so crash recovery never requires copying model
text into Journal metadata.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
import json
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.model.api import (
    ModelBindingSelectionReceipt,
    ProjectModelBinding,
    ProjectModelBindingSet,
    ProjectModelClientPort,
    ProjectModelRequest,
    ProjectModelResponse,
)
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation, ResearchProgramHost
from .runtime_module import RuntimeModule, RuntimeModuleBuilder, RuntimeProgramComposer


class ModelInvocationMode(StrEnum):
    SINGLE = "single"
    FALLBACK = "fallback"
    PANEL = "panel"


@dataclass(frozen=True, slots=True)
class ModelInvocationCandidate:
    binding_digest: str
    reason_code: str = "primary"

    def __post_init__(self) -> None:
        if (
            type(self.binding_digest) is not str
            or len(self.binding_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.binding_digest)
        ):
            raise ValueError("model invocation candidate binding_digest must be SHA-256")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("model invocation candidate reason_code is required")


@dataclass(frozen=True, slots=True)
class ModelInvocationProgram:
    program_id: str
    version: str
    mode: ModelInvocationMode
    candidates: tuple[ModelInvocationCandidate, ...]
    selector: str | None = None
    minimum_successes: int = 1
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id),
            ("version", self.version),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"model invocation {name} is required")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.mode, ModelInvocationMode):
            raise TypeError("model invocation mode must be ModelInvocationMode")
        if type(self.candidates) is not tuple or not self.candidates:
            raise ValueError("model invocation program requires candidates")
        if any(
            not isinstance(candidate, ModelInvocationCandidate)
            for candidate in self.candidates
        ):
            raise TypeError(
                "model invocation candidates must be ModelInvocationCandidate values"
            )
        digests = tuple(candidate.binding_digest for candidate in self.candidates)
        if len(digests) != len(set(digests)):
            raise ValueError("model invocation candidates must be unique")
        if self.mode is ModelInvocationMode.SINGLE and len(self.candidates) != 1:
            raise ValueError("single model invocation requires exactly one candidate")
        if type(self.minimum_successes) is not int or self.minimum_successes < 1:
            raise ValueError("model invocation minimum_successes must be positive")
        if self.minimum_successes > len(self.candidates):
            raise ValueError("model invocation minimum_successes exceeds candidates")
        if self.mode is not ModelInvocationMode.PANEL and self.minimum_successes != 1:
            raise ValueError(
                "minimum_successes is only configurable for panel invocation"
            )
        if self.mode is ModelInvocationMode.PANEL:
            if type(self.selector) is not str or not self.selector.strip():
                raise ValueError("panel model invocation requires selector")
            object.__setattr__(self, "selector", self.selector.strip())
        elif self.selector is not None:
            raise ValueError("single/fallback invocation must not declare selector")

        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "mode": self.mode.value,
                "candidates": tuple({
                    "binding_digest": candidate.binding_digest,
                    "reason_code": candidate.reason_code,
                } for candidate in self.candidates),
                "selector": self.selector,
                "minimum_successes": self.minimum_successes,
            }),
        )


@dataclass(frozen=True, slots=True)
class ModelSelectionRequest:
    program: ModelInvocationProgram
    input_digest: str
    responses: tuple[ProjectModelResponse, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.program, ModelInvocationProgram):
            raise TypeError("model selector request requires ModelInvocationProgram")
        if (
            type(self.input_digest) is not str
            or len(self.input_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.input_digest)
        ):
            raise ValueError("model selector input_digest must be SHA-256")
        if type(self.responses) is not tuple or not self.responses:
            raise ValueError("model selector request requires responses")
        if any(
            not isinstance(response, ProjectModelResponse)
            for response in self.responses
        ):
            raise TypeError(
                "model selector responses must be ProjectModelResponse values"
            )


ModelResponseSelector = Callable[[ModelSelectionRequest], ProjectModelResponse]


@runtime_checkable
class ModelInvocationRequestFactoryPort(Protocol):
    factory_id: str
    implementation_digest: str

    def build(
        self,
        binding: ProjectModelBinding,
        attempt_index: int,
    ) -> ProjectModelRequest: ...


@dataclass(frozen=True, slots=True)
class FunctionalModelInvocationRequestFactory(
    ModelInvocationRequestFactoryPort
):
    factory_id: str
    implementation_digest: str
    handler: Callable[[ProjectModelBinding, int], ProjectModelRequest]

    def __post_init__(self) -> None:
        if type(self.factory_id) is not str or not self.factory_id.strip():
            raise ValueError("model request factory_id is required")
        require_sha256(
            self.implementation_digest,
            "model request factory implementation_digest",
        )
        if not callable(self.handler):
            raise TypeError("model request factory handler must be callable")

    def build(
        self,
        binding: ProjectModelBinding,
        attempt_index: int,
    ) -> ProjectModelRequest:
        value = self.handler(binding, attempt_index)
        if not isinstance(value, ProjectModelRequest):
            raise TypeError(
                "model request factory handler must return ProjectModelRequest"
            )
        return value


@runtime_checkable
class ModelResponseSelectorRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, selector: str) -> ModelResponseSelector: ...


class ModelResponseSelectorRegistry(ModelResponseSelectorRegistryPort):
    def __init__(self) -> None:
        self._selectors: dict[str, tuple[ModelResponseSelector, str]] = {}
        self._lock = RLock()

    def register(
        self,
        selector: str,
        handler: ModelResponseSelector,
        *,
        implementation_digest: str,
    ) -> None:
        if type(selector) is not str or not selector.strip():
            raise ValueError("model response selector id is required")
        if not callable(handler):
            raise TypeError("model response selector handler must be callable")
        require_sha256(
            implementation_digest,
            "model response selector implementation_digest",
        )
        selector = selector.strip()
        with self._lock:
            current = self._selectors.get(selector)
            value = (handler, implementation_digest)
            if current is not None and current != value:
                raise ValueError(
                    f"model response selector already registered: {selector}"
                )
            self._selectors[selector] = value

    def resolve(self, selector: str) -> ModelResponseSelector:
        if type(selector) is not str or not selector.strip():
            raise ValueError("model response selector id is required")
        with self._lock:
            try:
                return self._selectors[selector.strip()][0]
            except KeyError as exc:
                raise KeyError(
                    f"unbound model response selector: {selector}"
                ) from exc

    def selectors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._selectors))

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (selector, implementation_digest)
                for selector, (_, implementation_digest)
                in sorted(self._selectors.items())
            ))


@dataclass(frozen=True, slots=True)
class ModelInvocationOutcome:
    program_digest: str
    input_digest: str
    selected: ProjectModelResponse
    responses: tuple[ProjectModelResponse, ...]
    failed_binding_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.selected not in self.responses:
            raise ValueError("selected model response must belong to response set")
        if (
            type(self.input_digest) is not str
            or len(self.input_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.input_digest)
        ):
            raise ValueError("model invocation input_digest must be SHA-256")

    @property
    def outcome_digest(self) -> str:
        return canonical_digest({
            "program_digest": self.program_digest,
            "input_digest": self.input_digest,
            "selected_response_digest": self.selected.response_digest,
            "selected_request_digest": self.selected.request_digest,
            "response_digests": tuple(
                response.response_digest for response in self.responses
            ),
            "request_digests": tuple(
                response.request_digest for response in self.responses
            ),
            "failed_binding_digests": self.failed_binding_digests,
        })


def _selection_payload(receipt: ModelBindingSelectionReceipt | None) -> JsonValue:
    if receipt is None:
        return None
    return {
        "request_digest": receipt.request_digest,
        "binding_set_digest": receipt.binding_set_digest,
        "selected_binding_digest": receipt.selected_binding_digest,
        "attempt_index": receipt.attempt_index,
        "reason_code": receipt.reason_code,
        "previous_selection_receipt_digest": (
            receipt.previous_selection_receipt_digest
        ),
        "evidence_refs": receipt.evidence_refs,
        "receipt_digest": receipt.receipt_digest,
    }


def _selection_from_payload(value: object) -> ModelBindingSelectionReceipt | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("model selection receipt payload must be an object")
    receipt = ModelBindingSelectionReceipt(
        request_digest=value["request_digest"],
        binding_set_digest=value["binding_set_digest"],
        selected_binding_digest=value["selected_binding_digest"],
        attempt_index=value["attempt_index"],
        reason_code=value["reason_code"],
        previous_selection_receipt_digest=value.get(
            "previous_selection_receipt_digest"
        ),
        evidence_refs=tuple(value.get("evidence_refs", ())),
    )
    if receipt.receipt_digest != value.get("receipt_digest"):
        raise ValueError("model selection receipt digest mismatch")
    return receipt


def _response_document(response: ProjectModelResponse) -> JsonObject:
    return {
        "request_digest": response.request_digest,
        "binding_digest": response.binding_digest,
        "response_digest": response.response_digest,
        "text": response.text,
        "tool_calls": response.tool_calls,
        "finish_reason": response.finish_reason,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "selection_receipt": _selection_payload(response.selection_receipt),
    }


def _decode_response(payload: bytes) -> ProjectModelResponse:
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise TypeError("stored model response must decode to an object")
    return ProjectModelResponse(
        request_digest=document["request_digest"],
        binding_digest=document["binding_digest"],
        response_digest=document["response_digest"],
        text=document["text"],
        tool_calls=document.get("tool_calls", ()),
        finish_reason=document.get("finish_reason"),
        input_tokens=document.get("input_tokens"),
        output_tokens=document.get("output_tokens"),
        selection_receipt=_selection_from_payload(
            document.get("selection_receipt")
        ),
    )


def _blob_ref_payload(ref: ArtifactBlobRef) -> JsonObject:
    return {
        "content_sha256": ref.content_sha256,
        "size_bytes": ref.size_bytes,
        "media_type": ref.media_type,
    }


def _blob_ref_from_payload(value: object) -> ArtifactBlobRef:
    if not isinstance(value, dict):
        raise TypeError("model response artifact reference must be an object")
    return ArtifactBlobRef(
        value["content_sha256"],
        value["size_bytes"],
        value["media_type"],
    )


@dataclass(slots=True)
class ModelInvocationRuntimeBinding:
    program: ModelInvocationProgram
    binding_set: ProjectModelBindingSet
    clients: tuple[ProjectModelClientPort, ...]
    input_digest: str
    request_factory: ModelInvocationRequestFactoryPort
    responses: ArtifactBlobStorePort
    selectors: ModelResponseSelectorRegistryPort | None = None
    last_error: BaseException | None = None
    outcome: ModelInvocationOutcome | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, ModelInvocationProgram):
            raise TypeError("model invocation binding requires ModelInvocationProgram")
        if not isinstance(self.binding_set, ProjectModelBindingSet):
            raise TypeError("model invocation binding requires ProjectModelBindingSet")
        if (
            type(self.input_digest) is not str
            or len(self.input_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.input_digest)
        ):
            raise ValueError("model invocation input_digest must be SHA-256")
        if not isinstance(
            self.request_factory,
            ModelInvocationRequestFactoryPort,
        ):
            raise TypeError(
                "model invocation request_factory must implement "
                "ModelInvocationRequestFactoryPort"
            )
        require_sha256(
            self.request_factory.implementation_digest,
            "model invocation request factory implementation_digest",
        )
        if not isinstance(self.responses, ArtifactBlobStorePort):
            raise TypeError("model invocation binding requires ArtifactBlobStorePort")
        if type(self.clients) is not tuple or not self.clients:
            raise ValueError("model invocation binding requires model clients")
        if any(
            not isinstance(client, ProjectModelClientPort)
            for client in self.clients
        ):
            raise TypeError(
                "model invocation clients must implement ProjectModelClientPort"
            )
        client_digests = tuple(client.binding.digest() for client in self.clients)
        if len(client_digests) != len(set(client_digests)):
            raise ValueError("model invocation client bindings must be unique")
        if set(client_digests) != set(self.binding_set.binding_digests):
            raise ValueError(
                "model invocation clients must exactly cover frozen binding set"
            )
        candidate_digests = tuple(
            candidate.binding_digest for candidate in self.program.candidates
        )
        if any(
            digest not in set(self.binding_set.binding_digests)
            for digest in candidate_digests
        ):
            raise ValueError(
                "model invocation program references binding outside admitted set"
            )
        if self.program.mode is ModelInvocationMode.PANEL:
            if self.selectors is None:
                raise ValueError("panel model invocation requires selector registry")
            if not isinstance(self.selectors, ModelResponseSelectorRegistryPort):
                raise TypeError("model selector registry is invalid")
            require_sha256(
                self.selectors.identity_digest,
                "model selector registry identity_digest",
            )

    @property
    def binding_digest(self) -> str:
        selectors = (
            self.selectors.selectors()
            if isinstance(self.selectors, ModelResponseSelectorRegistry)
            else ()
        )
        return canonical_digest({
            "model_invocation_program_digest": self.program.program_digest,
            "binding_set_digest": self.binding_set.binding_set_digest,
            "input_digest": self.input_digest,
            "request_factory": {
                "factory_id": self.request_factory.factory_id,
                "implementation_digest": (
                    self.request_factory.implementation_digest
                ),
            },
            "selectors": selectors,
            "selector_registry_digest": (
                None
                if self.selectors is None
                else self.selectors.identity_digest
            ),
        })

    def client_for(self, binding_digest: str) -> ProjectModelClientPort:
        matches = tuple(
            client
            for client in self.clients
            if client.binding.digest() == binding_digest
        )
        if len(matches) != 1:
            raise KeyError(
                f"no unique model client for binding digest {binding_digest}"
            )
        return matches[0]

    def request_for(
        self,
        binding: ProjectModelBinding,
        attempt_index: int,
    ) -> ProjectModelRequest:
        if not self.binding_set.contains(binding):
            raise ValueError("model request binding is outside admitted set")
        request = self.request_factory.build(binding, attempt_index)
        if not isinstance(request, ProjectModelRequest):
            raise TypeError(
                "model invocation request_factory must return ProjectModelRequest"
            )
        if request.requirement_digest != self.binding_set.requirement_digest:
            raise ValueError("model invocation request requirement drifted")
        if request.envelope.role != binding.role:
            raise ValueError("model invocation request role drifted")
        if request.envelope.model != binding.model:
            raise ValueError("model invocation request model identity drifted")
        if (
            request.envelope.prompt_generation_id != binding.prompt_generation_id
            or request.envelope.prompt_id != binding.prompt_id
            or request.envelope.prompt_digest != binding.prompt_digest
        ):
            raise ValueError("model invocation request prompt provenance drifted")
        return request


def _attempt_rows(request: ProgramNodeRequest) -> list[dict[str, JsonValue]]:
    value = thaw_json(request.data.get("model_attempts", ()))
    if not isinstance(value, (tuple, list)):
        raise TypeError("model invocation attempt ledger must be a sequence")
    if any(not isinstance(row, dict) for row in value):
        raise TypeError("model invocation attempt rows must be objects")
    return [dict(row) for row in value]


def _successful_responses(
    binding: ModelInvocationRuntimeBinding,
    rows: list[dict[str, JsonValue]],
) -> tuple[ProjectModelResponse, ...]:
    responses: list[ProjectModelResponse] = []
    for row in rows:
        ref_value = row.get("response_ref")
        if ref_value is None:
            continue
        ref = _blob_ref_from_payload(thaw_json(ref_value))
        response = _decode_response(binding.responses.get(ref))
        if response.response_digest != row.get("response_digest"):
            raise RuntimeError("stored model response digest drifted")
        responses.append(response)
    return tuple(responses)


def _attempt(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ModelInvocationRuntimeBinding):
        raise TypeError(
            "runtime.model.attempt requires ModelInvocationRuntimeBinding"
        )
    configuration = thaw_json(request.node.configuration)
    if not isinstance(configuration, dict):
        raise TypeError("model invocation node configuration must be an object")
    if (
        configuration.get("model_invocation_program_digest")
        != binding.program.program_digest
    ):
        raise ValueError("runtime ModelInvocationProgram identity drifted")

    rows = _attempt_rows(request)
    attempt_index = len(rows) + 1
    if attempt_index > len(binding.program.candidates):
        successes = _successful_responses(binding, rows)
        if len(successes) < binding.program.minimum_successes:
            return ProgramNodeResult(
                value={
                    "success_count": len(successes),
                    "attempt_count": len(rows),
                },
                status=MachineStatus.FAILED,
                state_update={
                    "model_invocation_failure": "insufficient_successes",
                },
                events=({
                    "type": "runtime_model_invocation_failed",
                    "reason": "insufficient_successes",
                    "attempt_count": len(rows),
                    "success_count": len(successes),
                },),
            )
        return ProgramNodeResult(
            value={"success_count": len(successes)},
            next_node="select",
        )

    candidate = binding.program.candidates[attempt_index - 1]
    client = binding.client_for(candidate.binding_digest)
    previous_receipt_digest = None
    evidence_refs: tuple[str, ...] = ()
    if rows:
        previous_receipt_digest = rows[-1].get("selection_receipt_digest")
        if type(previous_receipt_digest) is not str:
            raise RuntimeError("prior model attempt selection receipt is missing")
        previous_failure = rows[-1].get("failure_digest")
        previous_response = rows[-1].get("response_digest")
        causal = previous_failure if previous_failure is not None else previous_response
        if type(causal) is not str:
            raise RuntimeError("prior model attempt has no causal digest")
        evidence_refs = (f"model-attempt:{causal}",)

    model_request = binding.request_for(client.binding, attempt_index)
    receipt = binding.binding_set.selection_receipt(
        request_digest=model_request.request_digest,
        binding=client.binding,
        attempt_index=attempt_index,
        reason_code=candidate.reason_code,
        previous_selection_receipt_digest=previous_receipt_digest,
        evidence_refs=evidence_refs,
    )
    row: dict[str, JsonValue] = {
        "attempt_index": attempt_index,
        "binding_digest": candidate.binding_digest,
        "selection_receipt_digest": receipt.receipt_digest,
        "request_digest": model_request.request_digest,
        "reason_code": candidate.reason_code,
        "response_digest": None,
        "response_ref": None,
        "failure_type": None,
        "failure_digest": None,
    }

    try:
        response = client.complete(model_request)
    except Exception as exc:
        binding.last_error = exc
        failure_type = type(exc).__name__
        failure_digest = canonical_digest({
            "attempt_index": attempt_index,
            "binding_digest": candidate.binding_digest,
            "failure_type": failure_type,
        })
        row["failure_type"] = failure_type
        row["failure_digest"] = failure_digest
        rows.append(row)
        has_more = attempt_index < len(binding.program.candidates)
        prior_successes = len(_successful_responses(binding, rows[:-1]))
        if binding.program.mode is ModelInvocationMode.PANEL:
            if has_more:
                can_continue = True
                status = None
                next_node = "attempt"
            elif prior_successes >= binding.program.minimum_successes:
                can_continue = True
                status = None
                next_node = "select"
            else:
                can_continue = False
                status = MachineStatus.FAILED
                next_node = None
        else:
            can_continue = (
                binding.program.mode is ModelInvocationMode.FALLBACK
                and has_more
            )
            status = None if can_continue else MachineStatus.FAILED
            next_node = "attempt" if can_continue else None
        return ProgramNodeResult(
            value={
                "attempt_index": attempt_index,
                "binding_digest": candidate.binding_digest,
                "failure_type": failure_type,
                "failure_digest": failure_digest,
            },
            state_update={
                "model_attempts": tuple(rows),
                "model_invocation_failure": (
                    None if can_continue else "provider_attempt_failed"
                ),
            },
            next_node=next_node,
            status=status,
            events=({
                "type": "runtime_model_attempt_failed",
                "attempt_index": attempt_index,
                "binding_digest": candidate.binding_digest,
                "failure_type": failure_type,
                "failure_digest": failure_digest,
                "continuing": can_continue,
            },),
        )

    if not isinstance(response, ProjectModelResponse):
        raise TypeError(
            "ProjectModelClientPort.complete must return ProjectModelResponse"
        )
    if response.request_digest != model_request.request_digest:
        raise ValueError("model response request identity drifted")
    if response.binding_digest != candidate.binding_digest:
        raise ValueError("model response binding identity drifted")

    response = replace(response, selection_receipt=receipt)
    ref = binding.responses.put(
        canonical_bytes(_response_document(response)),
        media_type="application/vnd.noetrium.model-invocation-response+json",
    )
    row["response_digest"] = response.response_digest
    row["response_ref"] = _blob_ref_payload(ref)
    rows.append(row)

    if binding.program.mode in {
        ModelInvocationMode.SINGLE,
        ModelInvocationMode.FALLBACK,
    }:
        next_node = "select"
    else:
        next_node = (
            "attempt"
            if attempt_index < len(binding.program.candidates)
            else "select"
        )
    return ProgramNodeResult(
        value={
            "attempt_index": attempt_index,
            "binding_digest": candidate.binding_digest,
            "response_digest": response.response_digest,
            "response_ref": _blob_ref_payload(ref),
        },
        state_update={
            "model_attempts": tuple(rows),
            "model_invocation_failure": None,
        },
        next_node=next_node,
        events=({
            "type": "runtime_model_attempt_completed",
            "attempt_index": attempt_index,
            "binding_digest": candidate.binding_digest,
            "response_digest": response.response_digest,
            "response_ref": _blob_ref_payload(ref),
        },),
        artifact_refs=(ref.content_sha256,),
    )


def _select(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ModelInvocationRuntimeBinding):
        raise TypeError(
            "runtime.model.select requires ModelInvocationRuntimeBinding"
        )
    rows = _attempt_rows(request)
    responses = _successful_responses(binding, rows)
    if len(responses) < binding.program.minimum_successes:
        return ProgramNodeResult(
            value={
                "success_count": len(responses),
                "attempt_count": len(rows),
            },
            status=MachineStatus.FAILED,
            state_update={"model_invocation_failure": "insufficient_successes"},
            events=({
                "type": "runtime_model_invocation_failed",
                "reason": "insufficient_successes",
                "success_count": len(responses),
                "attempt_count": len(rows),
            },),
        )

    if binding.program.mode in {
        ModelInvocationMode.SINGLE,
        ModelInvocationMode.FALLBACK,
    }:
        selected = responses[0]
    else:
        if binding.selectors is None or binding.program.selector is None:
            raise RuntimeError("panel invocation selector is unavailable")
        selected = binding.selectors.resolve(binding.program.selector)(
            ModelSelectionRequest(
                binding.program,
                binding.input_digest,
                responses,
            )
        )
        if not isinstance(selected, ProjectModelResponse):
            raise TypeError(
                "model response selector must return ProjectModelResponse"
            )
        if selected not in responses:
            raise ValueError(
                "model response selector returned response outside panel"
            )

    failed = tuple(
        row["binding_digest"]
        for row in rows
        if row.get("failure_digest") is not None
    )
    outcome = ModelInvocationOutcome(
        program_digest=binding.program.program_digest,
        input_digest=binding.input_digest,
        selected=selected,
        responses=responses,
        failed_binding_digests=failed,
    )
    binding.outcome = outcome
    return ProgramNodeResult(
        value={
            "outcome_digest": outcome.outcome_digest,
            "selected_response_digest": selected.response_digest,
            "selected_binding_digest": selected.binding_digest,
            "response_digests": tuple(
                response.response_digest for response in responses
            ),
            "failed_binding_digests": failed,
        },
        state_update={
            "model_invocation_outcome_digest": outcome.outcome_digest,
            "selected_model_response_digest": selected.response_digest,
            "selected_model_binding_digest": selected.binding_digest,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_model_invocation_selected",
            "outcome_digest": outcome.outcome_digest,
            "selected_response_digest": selected.response_digest,
            "selected_binding_digest": selected.binding_digest,
            "response_count": len(responses),
            "failure_count": len(failed),
        },),
    )


def model_invocation_runtime_module(
    program: ModelInvocationProgram,
    *,
    module_id: str = "runtime.model-invocation",
) -> RuntimeModule:
    if not isinstance(program, ModelInvocationProgram):
        raise TypeError(
            "model invocation runtime module requires ModelInvocationProgram"
        )
    return (
        RuntimeModuleBuilder.event(module_id=module_id, entrypoint="attempt")
        .node(
            "attempt",
            "runtime.model.attempt",
            configuration={
                "model_invocation_program_id": program.program_id,
                "model_invocation_program_version": program.version,
                "model_invocation_program_digest": program.program_digest,
                "mode": program.mode.value,
            },
        )
        .node(
            "select",
            "runtime.model.select",
            configuration={
                "model_invocation_program_digest": program.program_digest,
                "selector": program.selector,
            },
        )
        .build()
    )


def model_invocation_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.model.attempt",
            _attempt,
            canonical_digest({
                "operation": "runtime.model.attempt",
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "runtime.model.select",
            _select,
            canonical_digest({
                "operation": "runtime.model.select",
                "implementation_revision": 1,
            }),
        ),
    )


class ModelInvocationRuntime:
    """Thin RuntimeMachine host; owns no model/provider authority."""

    def __init__(
        self,
        program: ModelInvocationProgram,
        *,
        journal: MachineJournalPort,
        responses: ArtifactBlobStorePort,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if not isinstance(program, ModelInvocationProgram):
            raise TypeError("model invocation runtime requires program")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("model invocation runtime requires MachineJournalPort")
        if not isinstance(responses, ArtifactBlobStorePort):
            raise TypeError(
                "model invocation runtime requires ArtifactBlobStorePort"
            )
        self.program = program
        self.responses = responses
        module = model_invocation_runtime_module(program)
        runtime_program = (
            RuntimeProgramComposer(
                program_id=f"runtime.model:{program.program_id}",
                version=program.version,
                state_schema="runtime.model-invocation.state.v1",
                entry_module=module.module_id,
            )
            .module(module)
            .build()
        )
        self._host = ResearchProgramHost(
            host_id="runtime.model-invocation",
            program=runtime_program,
            operations=model_invocation_runtime_operations(),
            journal=journal,
            snapshot_store=snapshot_store,
            max_steps=max(4, len(program.candidates) + 3),
            dependency_identity={
                "model_invocation_program_digest": program.program_digest,
            },
        )

    def invoke(
        self,
        *,
        run_id: str,
        invocation_id: str,
        binding_set: ProjectModelBindingSet,
        clients: tuple[ProjectModelClientPort, ...],
        input_digest: str,
        request_factory: ModelInvocationRequestFactoryPort,
        selectors: ModelResponseSelectorRegistryPort | None = None,
    ) -> ModelInvocationOutcome:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("model invocation run_id is required")
        if type(invocation_id) is not str or not invocation_id.strip():
            raise ValueError("model invocation_id is required")
        binding = ModelInvocationRuntimeBinding(
            self.program,
            binding_set,
            clients,
            input_digest,
            request_factory,
            self.responses,
            selectors,
        )
        invocation_digest = canonical_digest({
            "run_id": run_id,
            "invocation_id": invocation_id,
            "input_digest": input_digest,
            "program_digest": self.program.program_digest,
            "binding_set_digest": binding_set.binding_set_digest,
        })
        execution = self._host.execute(
            machine_id=(
                f"runtime-model:{run_id}:"
                f"{invocation_digest[:24]}"
            ),
            instance_identity={
                "run_id": run_id,
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "input_digest": input_digest,
                "program_digest": self.program.program_digest,
                "binding_set_digest": binding_set.binding_set_digest,
                "runtime_binding_digest": binding.binding_digest,
            },
            binding=binding,
            initial_data={
                "invocation_id": invocation_id,
                "invocation_digest": invocation_digest,
                "input_digest": input_digest,
                "model_invocation_program_digest": self.program.program_digest,
                "binding_set_digest": binding_set.binding_set_digest,
                "runtime_binding_digest": binding.binding_digest,
                "model_attempts": (),
            },
            payload={"source": "model-invocation"},
            command_id_prefix=f"runtime-model:{invocation_digest[:24]}",
        )
        if execution.status is MachineStatus.FAILED:
            if binding.last_error is not None:
                raise RuntimeError(
                    "model invocation exhausted admitted candidates"
                ) from binding.last_error
            raise RuntimeError(
                "model invocation RuntimeProgram entered FAILED state"
            )
        if execution.status is not MachineStatus.COMPLETED:
            raise RuntimeError(
                "model invocation RuntimeProgram stopped before completion: "
                f"{execution.status.value}"
            )
        if binding.outcome is None:
            # Crash-reopen path: reconstruct outcome from authoritative Machine data.
            rows_value = thaw_json(execution.data.get("model_attempts", ()))
            if not isinstance(rows_value, (tuple, list)):
                raise TypeError("model invocation attempts are invalid")
            rows = [dict(row) for row in rows_value if isinstance(row, dict)]
            responses = _successful_responses(binding, rows)
            selected_digest = execution.data.get(
                "selected_model_response_digest"
            )
            selected_rows = tuple(
                response
                for response in responses
                if response.response_digest == selected_digest
            )
            if len(selected_rows) != 1:
                raise RuntimeError(
                    "cannot reconstruct selected model response from Machine state"
                )
            failed = tuple(
                row["binding_digest"]
                for row in rows
                if row.get("failure_digest") is not None
            )
            binding.outcome = ModelInvocationOutcome(
                self.program.program_digest,
                input_digest,
                selected_rows[0],
                responses,
                failed,
            )
        return binding.outcome


__all__ = [
    "ModelInvocationCandidate",
    "ModelInvocationMode",
    "ModelInvocationOutcome",
    "FunctionalModelInvocationRequestFactory",
    "ModelInvocationProgram",
    "ModelInvocationRequestFactoryPort",
    "ModelInvocationRuntime",
    "ModelInvocationRuntimeBinding",
    "ModelResponseSelector",
    "ModelResponseSelectorRegistry",
    "ModelResponseSelectorRegistryPort",
    "ModelSelectionRequest",
    "model_invocation_runtime_module",
    "model_invocation_runtime_operations",
]
