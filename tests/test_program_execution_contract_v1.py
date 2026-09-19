from __future__ import annotations

from types import MappingProxyType

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import EffectCertainty
from noetrium_platform.research.execution.api import (
    ExecutableProgramIdentity,
    PublishedExecutableProgramSource,
    ProgramExecutionReceipt,
    ProgramExecutionRequest,
    ProgramExecutionStatus,
)


def _program(
    source_digest: str = "a" * 64,
    *,
    interface_schema_id: str = "paper.skill.v1",
) -> ExecutableProgramIdentity:
    return ExecutableProgramIdentity(
        program_id="paper.skill:mine-stone",
        source=PublishedExecutableProgramSource(
            identity=ArtifactContentIdentity(
                "artifact:paper.skill:mine-stone",
                source_digest,
            ),
            content=ArtifactBlobRef(
                content_sha256=source_digest,
                size_bytes=128,
                media_type="text/javascript",
            ),
        ),
        language="javascript",
        entrypoint="mineStone",
        interface_schema_id=interface_schema_id,
    )


def _request(**changes) -> ProgramExecutionRequest:
    values = {
        "program": _program(),
        "capability_surface_id": "minecraft.mineflayer.skill.v1",
        "capability_surface_digest": "b" * 64,
        "execution_target_digest": "c" * 64,
        "isolation_requirement_id": "sandbox.untrusted-javascript",
        "invocation": {
            "args": {"block": "stone", "count": 1},
            "attempt": 0,
        },
        "capability_ids": (
            "minecraft.collect-block",
            "minecraft.observe",
        ),
        "input_artifacts": (
            ArtifactContentIdentity("artifact:task", "d" * 64),
        ),
        "resource_requirement_digest": "e" * 64,
    }
    values.update(changes)
    return ProgramExecutionRequest(**values)


def test_published_executable_source_rejects_identity_blob_drift() -> None:
    with pytest.raises(ValueError, match="identity/content digest mismatch"):
        PublishedExecutableProgramSource(
            identity=ArtifactContentIdentity("artifact:source", "a" * 64),
            content=ArtifactBlobRef(
                content_sha256="b" * 64,
                size_bytes=1,
                media_type="text/javascript",
            ),
        )


def test_executable_program_identity_binds_source_and_public_interface() -> None:
    program = _program()
    changed_source = _program("f" * 64)
    changed_interface = _program(interface_schema_id="paper.skill.v2")

    assert program.program_digest != changed_source.program_digest
    assert program.program_digest != changed_interface.program_digest
    assert len(program.program_digest) == 64


def test_program_execution_request_binds_surface_target_and_invocation() -> None:
    request = _request()
    changed_surface = _request(capability_surface_digest="1" * 64)
    changed_target = _request(execution_target_digest="2" * 64)
    changed_invocation = _request(
        invocation={"args": {"block": "iron_ore", "count": 1}, "attempt": 0}
    )

    assert request.request_digest != changed_surface.request_digest
    assert request.request_digest != changed_target.request_digest
    assert request.request_digest != changed_invocation.request_digest
    assert isinstance(request.invocation, MappingProxyType)
    with pytest.raises(TypeError):
        request.invocation["attempt"] = 9


def test_program_execution_receipt_links_effect_and_isolation_evidence() -> None:
    request = _request()
    receipt = ProgramExecutionReceipt(
        request_digest=request.request_digest,
        status=ProgramExecutionStatus.SUCCEEDED,
        effect_certainty=EffectCertainty.EFFECT_CONFIRMED,
        output_artifacts=(
            ArtifactContentIdentity("artifact:stdout", "3" * 64),
        ),
        effect_receipt_digests=("4" * 64,),
        evidence_digests=("5" * 64,),
        isolation_evidence_digests=("6" * 64,),
    )

    assert receipt.effect_receipt_digests == ("4" * 64,)
    assert receipt.isolation_evidence_digests == ("6" * 64,)
    assert len(receipt.receipt_digest) == 64


@pytest.mark.parametrize(
    ("status", "certainty"),
    (
        (ProgramExecutionStatus.FAILED, EffectCertainty.EFFECT_UNKNOWN),
        (ProgramExecutionStatus.REJECTED, EffectCertainty.EFFECT_REJECTED),
    ),
)
def test_non_successful_program_execution_requires_failure_code(
    status,
    certainty,
) -> None:
    with pytest.raises(ValueError, match="requires failure_code"):
        ProgramExecutionReceipt(
            request_digest="7" * 64,
            status=status,
            effect_certainty=certainty,
        )
