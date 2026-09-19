from __future__ import annotations

from hashlib import sha256

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityRequest,
)
from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    ExecutionContext,
)
from noetrium_platform.research.execution.api import (
    PublishedExecutableProgramSource,
    ProgramExecutionReceipt,
    ProgramExecutionReconciliationDisposition,
    ProgramExecutionReconciliationResult,
    ProgramExecutionStatus,
)
from noetrium_platform.research.execution.runtime import (
    ProgramExecutionCapabilityBinding,
    program_execution_capability_payload,
)


class _SourcePublisher:
    def __init__(self) -> None:
        self.sources: list[str] = []

    def publish_source(self, *, program_id, language, source_text):
        self.sources.append(source_text)
        raw = source_text.encode("utf-8")
        digest = sha256(raw).hexdigest()
        return PublishedExecutableProgramSource(
            identity=ArtifactContentIdentity(
                f"artifact:{program_id}:{language}",
                digest,
            ),
            content=ArtifactBlobRef(
                content_sha256=digest,
                size_bytes=len(raw),
                media_type="text/javascript",
            ),
        )


class _Executor:
    def __init__(self) -> None:
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return ProgramExecutionReceipt(
            request_digest=request.request_digest,
            status=ProgramExecutionStatus.SUCCEEDED,
            effect_certainty=EffectCertainty.EFFECT_CONFIRMED,
            result={"observation": {"biome": "forest"}},
            output_artifacts=(
                ArtifactContentIdentity("artifact:stdout", "8" * 64),
            ),
            effect_receipt_digests=("9" * 64,),
            evidence_digests=("a" * 64,),
            isolation_evidence_digests=("b" * 64,),
        )


class _Recovery:
    effect_recovery_durability = "crash_durable"

    def __init__(self) -> None:
        self.requests = []

    def reconcile(self, request):
        self.requests.append(request)
        return ProgramExecutionReconciliationResult(
            request_digest=request.request_digest,
            disposition=ProgramExecutionReconciliationDisposition.APPLIED,
            receipt=ProgramExecutionReceipt(
                request_digest=request.request_digest,
                status=ProgramExecutionStatus.SUCCEEDED,
                effect_certainty=EffectCertainty.EFFECT_CONFIRMED,
                effect_receipt_digests=("9" * 64,),
                isolation_evidence_digests=("b" * 64,),
            ),
            evidence_digests=("c" * 64,),
        )


class _PossibleFailureExecutor:
    def execute(self, request):
        return ProgramExecutionReceipt(
            request_digest=request.request_digest,
            status=ProgramExecutionStatus.FAILED,
            effect_certainty=EffectCertainty.EFFECT_POSSIBLE,
            failure_code="PROGRAM_FAILED_AFTER_EFFECT_POSSIBLE",
        )


def _request() -> CapabilityRequest:
    return CapabilityRequest(
        capability_id="execution.program.execute",
        payload=program_execution_capability_payload(
            program_id="voyager.skill.mine-stone",
            source_text="async function mineStone(bot) { return true; }",
            language="javascript",
            entrypoint="mineStone",
            interface_schema_id="voyager.mineflayer.skill.v1",
            invocation={"expression": "await mineStone(bot);"},
        ),
        context=ExecutionContext(
            "program-run",
            "trace",
            "span",
            study_id="voyager",
            task_id="minecraft:lifelong",
        ),
        idempotency_key="voyager:skill:mine-stone:attempt:0",
    )


def test_program_execution_capability_freezes_source_and_effect_identity() -> None:
    publisher = _SourcePublisher()
    executor = _Executor()
    recovery = _Recovery()
    binding = ProgramExecutionCapabilityBinding(
        publisher,
        executor,
        recovery,
        capability_surface_id="minecraft.mineflayer.program.v1",
        capability_surface_digest="1" * 64,
        execution_target_digest="2" * 64,
        isolation_requirement_id="sandbox.untrusted-javascript",
        capability_ids=("minecraft.act", "minecraft.query"),
        resource_requirement_digest="3" * 64,
        provider_instance_id="sandbox-worker:test",
    )
    request = _request()

    handle = binding.prepare_capability_effect(request)
    result = binding.execute_prepared_capability(request, handle)

    assert publisher.sources == [
        "async function mineStone(bot) { return true; }"
    ]
    assert len(executor.requests) == 1
    execution = executor.requests[0]
    assert execution.program.source.identity.content_sha256 == sha256(
        publisher.sources[0].encode("utf-8")
    ).hexdigest()
    assert execution.program.source.content.size_bytes == len(
        publisher.sources[0].encode("utf-8")
    )
    assert execution.capability_surface_id == (
        "minecraft.mineflayer.program.v1"
    )
    assert execution.capability_ids == (
        "minecraft.act",
        "minecraft.query",
    )
    assert result.payload["status"] == "succeeded"
    assert result.payload["result"] == {
        "observation": {"biome": "forest"}
    }
    assert result.payload["effect_receipt_digests"] == ("9" * 64,)
    assert result.effect is not None
    assert result.effect.provider_receipt == (
        result.payload["execution_receipt_digest"]
    )
    assert result.artifacts == (
        execution.program.source.identity.artifact_id,
        "artifact:stdout",
    )


def test_program_execution_capability_reconciles_from_prepared_handle() -> None:
    binding = ProgramExecutionCapabilityBinding(
        _SourcePublisher(),
        _Executor(),
        _Recovery(),
        capability_surface_id="minecraft.mineflayer.program.v1",
        capability_surface_digest="1" * 64,
        execution_target_digest="2" * 64,
        isolation_requirement_id="sandbox.untrusted-javascript",
    )
    request = _request()
    handle = binding.prepare_capability_effect(request)

    reconciliation = binding.reconcile_prepared_capability(
        handle,
        request.context,
    )

    assert reconciliation.disposition.value == "applied"
    assert reconciliation.result is not None
    assert reconciliation.result.payload["status"] == "succeeded"
    assert reconciliation.diagnostics[
        "program_reconciliation_evidence_digests"
    ] == ("c" * 64,)


def test_program_execution_failure_does_not_collapse_possible_effect_to_no_effect() -> None:
    binding = ProgramExecutionCapabilityBinding(
        _SourcePublisher(),
        _PossibleFailureExecutor(),
        _Recovery(),
        capability_surface_id="minecraft.mineflayer.program.v1",
        capability_surface_digest="1" * 64,
        execution_target_digest="2" * 64,
        isolation_requirement_id="sandbox.untrusted-javascript",
    )
    request = _request()
    handle = binding.prepare_capability_effect(request)

    result = binding.execute_prepared_capability(request, handle)

    assert result.payload["status"] == "failed"
    assert result.payload["effect_certainty"] == "effect_possible"
    assert result.effect is not None
    assert result.effect.certainty is EffectCertainty.EFFECT_POSSIBLE
