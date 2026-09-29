from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRetention,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.research.execution.workflow.api import (
    MethodCheckpoint,
    MethodEvidenceStatus,
    MethodRunResult,
)
from noetrium_platform.research.execution.workflow.providers.method_evidence import (
    DirectoryEventMethodEvidence,
)
from .research_execution_content import ResearchExecutionContentAuthorities


@dataclass(slots=True)
class ArtifactBackedMethodEvidence:
    """Durable Method evidence carrier projected into the canonical Artifact authority."""

    directory: DirectoryEventMethodEvidence
    content: ResearchExecutionContentAuthorities

    def record_checkpoint(self, checkpoint: MethodCheckpoint) -> None:
        self.directory.record_checkpoint(checkpoint)

    def validate_result(
        self,
        result: MethodRunResult,
        obligations: tuple[str, ...],
    ) -> MethodEvidenceStatus:
        return self.directory.validate_result(result, obligations)

    def record_result(self, result: MethodRunResult) -> ArtifactReference:
        self.directory.record_result(result)
        return self.content.publish(
            reference_id="method-evidence:" + result.run_digest,
            scope=ScopeIdentity(ScopeKind.RUN, result.run_id),
            payload=canonical_bytes(
                {
                    "schema": "noetrium.method-evidence.authoritative.v1",
                    "run_digest": result.run_digest,
                    "result": result,
                }
            ),
            media_type="application/vnd.noetrium.method-evidence+json",
            kind=ArtifactKind.SCIENTIFIC,
            retention=ArtifactRetention.RUN,
            producer_component_id="method.evidence",
            metadata={
                "method_run_id": result.run_id,
                "method_run_digest": result.run_digest,
                "method_program_digest": result.program_digest,
                "evidence_status": result.evidence_status.value,
            },
        )


@dataclass(frozen=True, slots=True)
class ArtifactBackedMethodEvidenceFactory:
    content: ResearchExecutionContentAuthorities

    def __post_init__(self) -> None:
        if type(self.content) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "Artifact-backed Method evidence requires ResearchExecutionContentAuthorities"
            )

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "provider": "artifact-backed-method-evidence.v1",
                "content_authority": self.content.identity_digest,
            }
        )

    def create(self, root: str | Path) -> ArtifactBackedMethodEvidence:
        return ArtifactBackedMethodEvidence(
            DirectoryEventMethodEvidence(root),
            self.content,
        )


__all__ = [
    "ArtifactBackedMethodEvidence",
    "ArtifactBackedMethodEvidenceFactory",
]
