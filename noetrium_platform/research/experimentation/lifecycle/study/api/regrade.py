"""Artifact-only verifier regrade contracts.

Regrade is defined over a frozen Trial artifact cut.  It never mutates or
implicitly reuses the source verifier result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.execution.api import (
    ArtifactContentIdentity,
    ArtifactReference,
)

from .benchmark import TaskArtifactSpec

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return text


class TaskVerifierRegradeNotReady(RuntimeError):
    """The frozen source record cannot satisfy a target verifier input contract."""

    def __init__(self, code: str, message: str) -> None:
        _text(code, "verifier regrade failure code")
        self.code = code
        super().__init__(f"verifier regrade not ready [{code}]: {message}")


@dataclass(frozen=True, slots=True)
class TaskVerifierArtifactBinding:
    """One task-declared verifier input bound to verified immutable content."""

    declaration: TaskArtifactSpec
    reference: ArtifactReference
    content_identity: ArtifactContentIdentity
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.declaration) is not TaskArtifactSpec:
            raise TypeError("verifier regrade binding declaration must be TaskArtifactSpec")
        if type(self.reference) is not ArtifactReference:
            raise TypeError("verifier regrade binding reference must be ArtifactReference")
        if type(self.content_identity) is not ArtifactContentIdentity:
            raise TypeError(
                "verifier regrade binding content_identity must be ArtifactContentIdentity"
            )
        if self.reference.artifact_id != self.content_identity.artifact_id:
            raise ValueError(
                "verifier regrade binding reference/content artifact identity drift"
            )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "declaration": self.declaration,
                    "reference": self.reference,
                    "content_identity": self.content_identity,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskVerifierRegradeDefinition:
    """Frozen target verifier identity over one source Trial artifact cut."""

    regrade_id: str
    source_trial_receipt_digest: str
    source_artifact_cut_digest: str
    verifier_requirement_id: str
    verifier_implementation_digest: str
    output_protocol_semantic_digest: str
    required_artifacts: tuple[TaskArtifactSpec, ...]
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.regrade_id, "verifier regrade regrade_id")
        _sha(
            self.source_trial_receipt_digest,
            "verifier regrade source_trial_receipt_digest",
        )
        _sha(
            self.source_artifact_cut_digest,
            "verifier regrade source_artifact_cut_digest",
        )
        _text(
            self.verifier_requirement_id,
            "verifier regrade verifier_requirement_id",
        )
        _sha(
            self.verifier_implementation_digest,
            "verifier regrade verifier_implementation_digest",
        )
        _sha(
            self.output_protocol_semantic_digest,
            "verifier regrade output_protocol_semantic_digest",
        )
        if type(self.required_artifacts) is not tuple or not self.required_artifacts:
            raise TypeError(
                "verifier regrade required_artifacts must be a non-empty tuple"
            )
        if any(type(row) is not TaskArtifactSpec for row in self.required_artifacts):
            raise TypeError(
                "verifier regrade required_artifacts must contain TaskArtifactSpec"
            )
        ordered = tuple(
            sorted(self.required_artifacts, key=lambda row: row.artifact_id)
        )
        ids = tuple(row.artifact_id for row in ordered)
        paths = tuple(row.relative_path for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("verifier regrade required artifact ids must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("verifier regrade required artifact paths must be unique")
        object.__setattr__(self, "required_artifacts", ordered)
        object.__setattr__(
            self,
            "definition_digest",
            canonical_digest(
                {
                    "regrade_id": self.regrade_id,
                    "source_trial_receipt_digest": self.source_trial_receipt_digest,
                    "source_artifact_cut_digest": self.source_artifact_cut_digest,
                    "verifier_requirement_id": self.verifier_requirement_id,
                    "verifier_implementation_digest": (
                        self.verifier_implementation_digest
                    ),
                    "output_protocol_semantic_digest": (
                        self.output_protocol_semantic_digest
                    ),
                    "required_artifacts": ordered,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskVerifierRegradeProof:
    """Content-authority proof that a target verifier can regrade the source."""

    definition_digest: str
    source_trial_receipt_digest: str
    source_artifact_cut_digest: str
    artifact_bindings: tuple[TaskVerifierArtifactBinding, ...]
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.definition_digest, "verifier regrade proof definition_digest")
        _sha(
            self.source_trial_receipt_digest,
            "verifier regrade proof source_trial_receipt_digest",
        )
        _sha(
            self.source_artifact_cut_digest,
            "verifier regrade proof source_artifact_cut_digest",
        )
        if type(self.artifact_bindings) is not tuple or not self.artifact_bindings:
            raise TypeError(
                "verifier regrade proof artifact_bindings must be a non-empty tuple"
            )
        if any(
            type(row) is not TaskVerifierArtifactBinding
            for row in self.artifact_bindings
        ):
            raise TypeError(
                "verifier regrade proof bindings must contain "
                "TaskVerifierArtifactBinding"
            )
        ordered = tuple(
            sorted(
                self.artifact_bindings,
                key=lambda row: row.declaration.artifact_id,
            )
        )
        ids = tuple(row.declaration.artifact_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("verifier regrade proof artifact bindings must be unique")
        object.__setattr__(self, "artifact_bindings", ordered)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "definition_digest": self.definition_digest,
                    "source_trial_receipt_digest": self.source_trial_receipt_digest,
                    "source_artifact_cut_digest": self.source_artifact_cut_digest,
                    "artifact_bindings": tuple(
                        row.binding_digest for row in ordered
                    ),
                }
            ),
        )


__all__ = [
    "TaskVerifierArtifactBinding",
    "TaskVerifierRegradeDefinition",
    "TaskVerifierRegradeNotReady",
    "TaskVerifierRegradeProof",
]
