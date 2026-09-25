from __future__ import annotations

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.governance.architecture.api import (
    QualificationEvidence,
    QualificationKind,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty
from noetrium_platform.research.execution.api import (
    ExecutableProgramIdentity,
    PublishedExecutableProgramSource,
    ProgramExecutionReceipt,
    ProgramExecutionReconciliationDisposition,
    ProgramExecutionReconciliationResult,
    ProgramExecutionRequest,
    ProgramExecutionStatus,
)
from noetrium_platform.research.execution.composition import (
    QualifiedProgramExecutionBinding,
)


def _request() -> ProgramExecutionRequest:
    program = ExecutableProgramIdentity(
        program_id="voyager.skill.mine-stone",
        source=PublishedExecutableProgramSource(
            identity=ArtifactContentIdentity("artifact:source", "a" * 64),
            content=ArtifactBlobRef(
                content_sha256="a" * 64,
                size_bytes=64,
                media_type="text/javascript",
            ),
        ),
        language="javascript",
        entrypoint="mineStone",
        interface_schema_id="minecraft.mineflayer.program.v1",
    )
    return ProgramExecutionRequest(
        program=program,
        capability_surface_id="minecraft.mineflayer.program.v1",
        capability_surface_digest="b" * 64,
        execution_target_digest="c" * 64,
        isolation_requirement_id="sandbox.untrusted-javascript",
        invocation={"expression": "await mineStone(bot);"},
        capability_ids=("minecraft.act", "minecraft.query"),
        resource_requirement_digest="d" * 64,
    )


class _Executor:
    def __init__(self) -> None:
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return ProgramExecutionReceipt(
            request_digest=request.request_digest,
            status=ProgramExecutionStatus.SUCCEEDED,
            effect_certainty=EffectCertainty.NO_EFFECT,
            result={"observation": {"inventoryUsed": 1}},
            evidence_digests=("4" * 64,),
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
                effect_certainty=EffectCertainty.NO_EFFECT,
            ),
            evidence_digests=("5" * 64,),
        )


class _Qualification:
    def __init__(self, rows=None) -> None:
        self.calls = []
        self.rows = rows or (
            QualificationEvidence(
                QualificationKind.CONSENSUS,
                "qualifier",
                "1",
                "1" * 64,
            ),
            QualificationEvidence(
                QualificationKind.WORKER_ATTESTATION,
                "qualifier",
                "1",
                "2" * 64,
            ),
            QualificationEvidence(
                QualificationKind.ISOLATION,
                "qualifier",
                "1",
                "3" * 64,
                constraints=("sandbox.untrusted-javascript",),
            ),
        )

    def qualify(self, machine_id, worker_id, workload_id):
        self.calls.append((machine_id, worker_id, workload_id))
        return self.rows


def _binding(qualification=None):
    executor = _Executor()
    recovery = _Recovery()
    qualifier = qualification or _Qualification()
    binding = QualifiedProgramExecutionBinding(
        executor,
        recovery,
        qualifier,
        machine_id="method:voyager",
        worker_id="sandbox-worker:1",
    )
    return binding, executor, recovery, qualifier


def test_qualified_program_execution_binds_exact_workload_evidence() -> None:
    binding, executor, _, qualifier = _binding()
    request = _request()

    receipt = binding.execute(request)

    assert qualifier.calls == [
        ("method:voyager", "sandbox-worker:1", request.request_digest)
    ]
    assert executor.requests == [request]
    assert receipt.evidence_digests == (
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
    )
    assert receipt.isolation_evidence_digests == ("3" * 64,)
    assert receipt.result == {"observation": {"inventoryUsed": 1}}


def test_qualified_program_recovery_rebinds_qualification_evidence() -> None:
    binding, _, recovery, qualifier = _binding()
    request = _request()

    result = binding.reconcile(request)

    assert recovery.requests == [request]
    assert qualifier.calls == [
        ("method:voyager", "sandbox-worker:1", request.request_digest)
    ]
    assert result.receipt is not None
    assert result.receipt.isolation_evidence_digests == ("3" * 64,)
    assert result.evidence_digests == (
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "5" * 64,
    )


def test_qualified_program_execution_fails_closed_before_provider_call() -> None:
    incomplete = _Qualification(
        rows=(
            QualificationEvidence(
                QualificationKind.ISOLATION,
                "qualifier",
                "1",
                "3" * 64,
            ),
        )
    )
    binding, executor, _, _ = _binding(incomplete)

    with pytest.raises(
        ValueError,
        match="consensus, attestation and isolation",
    ):
        binding.execute(_request())

    assert executor.requests == []
