from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

import json
from collections.abc import Mapping

from noetrium_platform.capabilities.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.capabilities.api import ArtifactContentIdentity
from noetrium_platform.capabilities.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.capabilities.api import (
    prepared_effect_handle,
    prepared_handle_field,
)

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    JsonInput,
    JsonValue,
    thaw_json,
)
from noetrium_platform.capabilities.api import (
    EffectReconciliationDisposition,
)
from noetrium_platform.research.execution.api import (
    executable_program_unit,
    executable_program_field,
    require_executable_program,
    ExecutableUnitSourcePublicationPort,
    PublishedExecutableUnitSource,
    ProgramExecutionPort,
    ProgramExecutionReceipt,
    ProgramExecutionReconciliationDisposition,
    ProgramExecutionRecoveryPort,
    ProgramExecutionRequest,
    ProgramExecutionStatus,
)

_CAPABILITY_ID = "execution.program.execute"
_REQUEST_SCHEMA = "noetrium.program-execution-capability.request.v1"
_RESULT_SCHEMA = "noetrium.program-execution-capability.result.v1"
_HANDLE_SCHEMA = "noetrium.program-execution-capability.handle.v1"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, tuple):
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(_text(item, field) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


def _artifact_document(value: ArtifactContentIdentity) -> dict[str, str]:
    return {
        "artifact_id": value.artifact_id,
        "content_sha256": value.content_sha256,
    }


def _artifact_from_document(value: object, field: str) -> ArtifactContentIdentity:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return ArtifactContentIdentity(
        _text(value.get("artifact_id"), f"{field}.artifact_id"),
        _text(value.get("content_sha256"), f"{field}.content_sha256"),
    )


def _source_document(
    value: PublishedExecutableUnitSource,
) -> dict[str, JsonInput]:
    return {
        "identity": _artifact_document(value.identity),
        "content": {
            "content_sha256": value.content.content_sha256,
            "size_bytes": value.content.size_bytes,
            "media_type": value.content.media_type,
        },
    }


def _source_from_document(
    value: object,
    field: str,
) -> PublishedExecutableUnitSource:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    identity = _artifact_from_document(
        value.get("identity"),
        f"{field}.identity",
    )
    content = value.get("content")
    if not isinstance(content, Mapping):
        raise TypeError(f"{field}.content must be an object")
    size_bytes = content.get("size_bytes")
    if type(size_bytes) is not int:
        raise TypeError(f"{field}.content.size_bytes must be integer")
    return PublishedExecutableUnitSource(
        identity=identity,
        content=ArtifactBlobRef(
            content_sha256=_text(
                content.get("content_sha256"),
                f"{field}.content.content_sha256",
            ),
            size_bytes=size_bytes,
            media_type=_text(
                content.get("media_type"),
                f"{field}.content.media_type",
            ),
        ),
    )


def _execution_request_document(
    request: ProgramExecutionRequest,
) -> dict[str, JsonInput]:
    return {
        "program": {
            "program_id": request.unit.unit_id,
            "source": _source_document(request.source),
            "language": str(executable_program_field(request.unit, "language")),
            "entrypoint": str(executable_program_field(request.unit, "entrypoint")),
            "interface_schema_id": str(executable_program_field(request.unit, "interface_schema_id")),
            "parent_program_digests": tuple(executable_program_field(request.unit, "parent_program_digests")),
        },
        "capability_surface_id": request.capability_surface_id,
        "capability_surface_digest": request.capability_surface_digest,
        "execution_target_digest": request.execution_target_digest,
        "isolation_requirement_id": request.isolation_requirement_id,
        "invocation": thaw_json(request.invocation),
        "capability_ids": request.capability_ids,
        "input_artifacts": tuple(
            _artifact_document(row) for row in request.input_artifacts
        ),
        "resource_requirement_digest": request.resource_requirement_digest,
    }


def _execution_request_from_document(value: object) -> ProgramExecutionRequest:
    if not isinstance(value, Mapping):
        raise TypeError("program execution prepared request must be an object")
    program_value = value.get("program")
    if not isinstance(program_value, Mapping):
        raise TypeError("program execution prepared request requires program")
    source = _source_from_document(
        program_value.get("source"),
        "program execution prepared source",
    )
    program = executable_program_unit(
        program_id=_text(
            program_value.get("program_id"),
            "program execution prepared program_id",
        ),
        source=source,
        language=_text(
            program_value.get("language"),
            "program execution prepared language",
        ),
        entrypoint=_text(
            program_value.get("entrypoint"),
            "program execution prepared entrypoint",
        ),
        interface_schema_id=_text(
            program_value.get("interface_schema_id"),
            "program execution prepared interface_schema_id",
        ),
        parent_program_digests=_string_tuple(
            tuple(program_value.get("parent_program_digests", ())),
            "program execution prepared parent_program_digests",
        ),
    )
    raw_inputs = value.get("input_artifacts", ())
    if not isinstance(raw_inputs, (tuple, list)):
        raise TypeError(
            "program execution prepared input_artifacts must be a sequence"
        )
    inputs = tuple(
        _artifact_from_document(
            row,
            "program execution prepared input artifact",
        )
        for row in raw_inputs
    )
    invocation = value.get("invocation", {})
    if not isinstance(invocation, Mapping):
        raise TypeError("program execution prepared invocation must be object")
    capability_ids = value.get("capability_ids", ())
    if not isinstance(capability_ids, (tuple, list)):
        raise TypeError(
            "program execution prepared capability_ids must be a sequence"
        )
    resource = value.get("resource_requirement_digest")
    return ProgramExecutionRequest(
        program=program,
        source=source,
        capability_surface_id=_text(
            value.get("capability_surface_id"),
            "program execution prepared capability_surface_id",
        ),
        capability_surface_digest=_text(
            value.get("capability_surface_digest"),
            "program execution prepared capability_surface_digest",
        ),
        execution_target_digest=_text(
            value.get("execution_target_digest"),
            "program execution prepared execution_target_digest",
        ),
        isolation_requirement_id=_text(
            value.get("isolation_requirement_id"),
            "program execution prepared isolation_requirement_id",
        ),
        invocation=dict(invocation),
        capability_ids=tuple(str(row) for row in capability_ids),
        input_artifacts=inputs,
        resource_requirement_digest=(
            None if resource is None else str(resource)
        ),
    )


class ProgramExecutionCapabilityBinding:
    """Expose isolated program execution through the common capability ABI.

    The binding owns no program source, sandbox state, environment state, or
    effect truth. Source bytes are first published to Artifact authority.
    Provider execution is crash-reconciled by ProgramExecutionRecoveryPort.
    """

    def __init__(
        self,
        source_publisher: ExecutableUnitSourcePublicationPort,
        executor: ProgramExecutionPort,
        recovery: ProgramExecutionRecoveryPort,
        *,
        capability_surface_id: str,
        capability_surface_digest: str,
        execution_target_digest: str,
        isolation_requirement_id: str,
        capability_ids: tuple[str, ...] = (),
        resource_requirement_digest: str | None = None,
        provider_instance_id: str | None = None,
        capability_id: str = _CAPABILITY_ID,
    ) -> None:
        if not isinstance(
            source_publisher,
            ExecutableUnitSourcePublicationPort,
        ):
            raise TypeError(
                "program execution capability requires source publisher"
            )
        if not isinstance(executor, ProgramExecutionPort):
            raise TypeError("program execution capability requires executor")
        if not isinstance(recovery, ProgramExecutionRecoveryPort):
            raise TypeError(
                "program execution capability requires recovery port"
            )
        if recovery.effect_recovery_durability != "crash_durable":
            raise ValueError(
                "program execution capability requires crash-durable recovery"
            )
        self._source_publisher = source_publisher
        self._executor = executor
        self._recovery = recovery
        self._capability_surface_id = _text(
            capability_surface_id,
            "program execution capability_surface_id",
        )
        self._capability_surface_digest = _text(
            capability_surface_digest,
            "program execution capability_surface_digest",
        )
        self._execution_target_digest = _text(
            execution_target_digest,
            "program execution execution_target_digest",
        )
        self._isolation_requirement_id = _text(
            isolation_requirement_id,
            "program execution isolation_requirement_id",
        )
        self._capability_ids = _string_tuple(
            capability_ids,
            "program execution capability_ids",
        )
        self._resource_requirement_digest = (
            None
            if resource_requirement_digest is None
            else _text(
                resource_requirement_digest,
                "program execution resource_requirement_digest",
            )
        )
        self._provider_instance_id = (
            None
            if provider_instance_id is None
            else _text(
                provider_instance_id,
                "program execution provider_instance_id",
            )
        )
        capability_id = _text(
            capability_id,
            "program execution capability_id",
        )
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.RECONCILABLE,
            deterministic=False,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    @property
    def effect_recovery_durability(self) -> str:
        return "crash_durable"

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest, control: ExecutionControlPort) -> CapabilityResult:
        control.checkpoint()
        del request
        raise RuntimeError(
            "effectful program execution must use CapabilityEffectExecutor"
        )

    def _program_request(
        self,
        request: CapabilityRequest,
    ) -> ProgramExecutionRequest:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TypeError(
                "program execution capability payload must be an object"
            )
        source_text = payload.get("source_text")
        if type(source_text) is not str or not source_text:
            raise ValueError(
                "program execution capability requires source_text"
            )
        program_id = _text(
            payload.get("program_id"),
            "program execution capability program_id",
        )
        language = _text(
            payload.get("language"),
            "program execution capability language",
        )
        source = self._source_publisher.publish_source(
            program_id=program_id,
            language=language,
            source_text=source_text,
        )
        if type(source) is not PublishedExecutableUnitSource:
            raise TypeError(
                "program source publisher must return "
                "PublishedExecutableUnitSource"
            )
        raw_parents = payload.get("parent_program_digests", ())
        if not isinstance(raw_parents, (tuple, list)):
            raise TypeError(
                "program execution parent_program_digests must be sequence"
            )
        raw_inputs = payload.get("input_artifacts", ())
        if not isinstance(raw_inputs, (tuple, list)):
            raise TypeError(
                "program execution input_artifacts must be sequence"
            )
        invocation = payload.get("invocation", {})
        if not isinstance(invocation, Mapping):
            raise TypeError(
                "program execution capability invocation must be object"
            )
        program = executable_program_unit(
            program_id=program_id,
            source=source,
            language=language,
            entrypoint=_text(
                payload.get("entrypoint"),
                "program execution capability entrypoint",
            ),
            interface_schema_id=_text(
                payload.get("interface_schema_id"),
                "program execution capability interface_schema_id",
            ),
            parent_program_digests=tuple(str(row) for row in raw_parents),
        )
        return ProgramExecutionRequest(
            program=program,
            source=source,
            capability_surface_id=self._capability_surface_id,
            capability_surface_digest=self._capability_surface_digest,
            execution_target_digest=self._execution_target_digest,
            isolation_requirement_id=self._isolation_requirement_id,
            invocation=dict(invocation),
            capability_ids=self._capability_ids,
            input_artifacts=tuple(
                _artifact_from_document(
                    row,
                    "program execution capability input artifact",
                )
                for row in raw_inputs
            ),
            resource_requirement_digest=self._resource_requirement_digest,
        )

    def prepare_capability_effect(
        self,
        request: CapabilityRequest,
        control: ExecutionControlPort,
    ) -> NoetriumUnit:
        control.checkpoint()
        program_request = self._program_request(request)
        payload = json.dumps(
            _execution_request_document(program_request),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return prepared_effect_handle(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema=_HANDLE_SCHEMA,
            opaque_payload=payload,
            provider_instance_id=self._provider_instance_id,
        )

    def execute_prepared_capability(
        self,
        request: CapabilityRequest,
        handle: NoetriumUnit,
        control: ExecutionControlPort,
    ) -> CapabilityResult:
        control.checkpoint()
        self._require_handle(request, handle)
        program_request = self._decode_handle(handle)
        receipt = self._executor.execute(program_request)
        control.checkpoint()
        self._require_receipt(program_request, receipt)
        return self._capability_result(
            program_request,
            receipt,
            capability_request_digest(request),
            capability_effect_request_id(request),
        )

    def reconcile_prepared_capability(
        self,
        handle: NoetriumUnit,
        context,
        control: ExecutionControlPort,
    ) -> CapabilityEffectReconciliationResult:
        control.checkpoint()
        del context
        self._require_handle_identity(handle)
        program_request = self._decode_handle(handle)
        reconciliation = self._recovery.reconcile(program_request)
        if reconciliation.request_digest != program_request.request_digest:
            raise ValueError(
                "program execution recovery request identity mismatch"
            )
        mapped = {
            ProgramExecutionReconciliationDisposition.APPLIED:
                EffectReconciliationDisposition.APPLIED,
            ProgramExecutionReconciliationDisposition.REJECTED:
                EffectReconciliationDisposition.REJECTED,
            ProgramExecutionReconciliationDisposition.NOT_APPLIED:
                EffectReconciliationDisposition.NOT_APPLIED,
            ProgramExecutionReconciliationDisposition.UNKNOWN:
                EffectReconciliationDisposition.UNKNOWN,
        }[reconciliation.disposition]
        result = None
        if reconciliation.receipt is not None:
            self._require_receipt(
                program_request,
                reconciliation.receipt,
            )
            result = self._capability_result(
                program_request,
                reconciliation.receipt,
                str(prepared_handle_field(handle, "request_digest")),
                str(prepared_handle_field(handle, "request_id")),
            )
        elif mapped is EffectReconciliationDisposition.UNKNOWN:
            result = CapabilityResult(
                capability_id=self._descriptor.capability_id,
                payload={
                    "status": "indeterminate",
                    "program_execution_request_digest": program_request.request_digest,
                },
                diagnostics={
                    "program_reconciliation_evidence_digests": reconciliation.evidence_digests,
                },
                effect=EffectReceipt(
                    effect_id=str(prepared_handle_field(handle, "request_id")),
                    request_digest=str(prepared_handle_field(handle, "request_digest")),
                    effect_class=EffectClass.RECONCILABLE,
                    certainty=EffectCertainty.INDETERMINATE,
                    provider_instance_id=self._provider_instance_id,
                    provider_receipt=str(prepared_handle_field(handle, "request_id")),
                ),
                request_digest=str(prepared_handle_field(handle, "request_digest")),
            )
        return CapabilityEffectReconciliationResult(
            capability_id=self._descriptor.capability_id,
            disposition=mapped,
            result=result,
            diagnostics={
                "program_execution_request_digest": (
                    program_request.request_digest
                ),
                "program_reconciliation_evidence_digests": (
                    reconciliation.evidence_digests
                ),
            },
        )

    def _decode_handle(
        self,
        handle: NoetriumUnit,
    ) -> ProgramExecutionRequest:
        self._require_handle_identity(handle)
        value = json.loads(prepared_handle_field(handle, "opaque_payload").decode("utf-8"))
        return _execution_request_from_document(value)

    def _require_handle_identity(
        self,
        handle: NoetriumUnit,
    ) -> None:
        if type(handle) is not NoetriumUnit:
            raise TypeError(
                "program execution capability requires NoetriumUnit"
            )
        if prepared_handle_field(handle, "provider_schema") != _HANDLE_SCHEMA:
            raise ValueError(
                "program execution capability handle schema mismatch"
            )

    def _require_handle(
        self,
        request: CapabilityRequest,
        handle: NoetriumUnit,
    ) -> None:
        self._require_handle_identity(handle)
        if str(prepared_handle_field(handle, "request_id")) != capability_effect_request_id(request):
            raise ValueError(
                "program execution capability handle request id mismatch"
            )
        if str(prepared_handle_field(handle, "request_digest")) != capability_request_digest(request):
            raise ValueError(
                "program execution capability handle request digest mismatch"
            )

    @staticmethod
    def _require_receipt(
        request: ProgramExecutionRequest,
        receipt: ProgramExecutionReceipt,
    ) -> None:
        if not isinstance(receipt, ProgramExecutionReceipt):
            raise TypeError(
                "program execution provider must return ProgramExecutionReceipt"
            )
        if receipt.request_digest != request.request_digest:
            raise ValueError(
                "program execution provider receipt identity mismatch"
            )

    def _capability_result(
        self,
        request: ProgramExecutionRequest,
        receipt: ProgramExecutionReceipt,
        outer_request_digest: str,
        outer_effect_id: str,
    ) -> CapabilityResult:
        effect = EffectReceipt(
            effect_id=outer_effect_id,
            request_digest=outer_request_digest,
            effect_class=EffectClass.RECONCILABLE,
            certainty=receipt.effect_certainty,
            provider_instance_id=self._provider_instance_id,
            provider_receipt=receipt.receipt_digest,
        )
        artifacts = (
            request.source.identity.artifact_id,
            *tuple(row.artifact_id for row in receipt.output_artifacts),
        )
        return CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "program_digest": request.unit.unit_digest,
                "source_artifact": _artifact_document(
                    request.source.identity
                ),
                "source_content": {
                    "content_sha256": (
                        request.source.content.content_sha256
                    ),
                    "size_bytes": request.source.content.size_bytes,
                    "media_type": request.source.content.media_type,
                },
                "execution_request_digest": request.request_digest,
                "execution_receipt_digest": receipt.receipt_digest,
                "status": receipt.status.value,
                "effect_certainty": receipt.effect_certainty.value,
                "result": receipt.result,
                "output_artifacts": tuple(
                    _artifact_document(row)
                    for row in receipt.output_artifacts
                ),
                "effect_receipt_digests": receipt.effect_receipt_digests,
                "evidence_digests": receipt.evidence_digests,
                "isolation_evidence_digests": (
                    receipt.isolation_evidence_digests
                ),
                "failure_code": receipt.failure_code,
            },
            artifacts=artifacts,
            diagnostics={
                "capability_surface_id": request.capability_surface_id,
                "capability_surface_digest": (
                    request.capability_surface_digest
                ),
                "execution_target_digest": request.execution_target_digest,
                "isolation_requirement_id": (
                    request.isolation_requirement_id
                ),
            },
            effect=effect,
            request_digest=outer_request_digest,
        )


__all__ = [
    "ProgramExecutionCapabilityBinding",
]
