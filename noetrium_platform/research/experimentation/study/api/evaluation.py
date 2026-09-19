"""Post-hoc evaluation identity over frozen execution/evidence cuts.

Evaluation is separate from original execution identity. Rebinding an
evaluation/grader model creates a new evaluation identity while preserving the
source execution digest.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentModelRoleSpec,
)

from .analysis import MeasurementCut
from .measurement import MeasurementProtocol

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


@dataclass(frozen=True, slots=True)
class PostHocEvaluationDefinition:
    evaluation_id: str
    evaluator_id: str
    evaluator_version: str
    implementation_digest: str
    configuration_digest: str
    source_execution_digest: str
    input_cut: MeasurementCut
    output_protocol: MeasurementProtocol
    model_roles: tuple[ExperimentModelRoleSpec, ...] = ()
    evaluation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("evaluation_id", self.evaluation_id),
            ("evaluator_id", self.evaluator_id),
            ("evaluator_version", self.evaluator_version),
        ):
            _text(value, f"post-hoc evaluation {name}")
        for name, value in (
            ("implementation_digest", self.implementation_digest),
            ("configuration_digest", self.configuration_digest),
            ("source_execution_digest", self.source_execution_digest),
        ):
            _sha(value, f"post-hoc evaluation {name}")
        if type(self.input_cut) is not MeasurementCut:
            raise TypeError("post-hoc evaluation input_cut must be MeasurementCut")
        if type(self.output_protocol) is not MeasurementProtocol:
            raise TypeError(
                "post-hoc evaluation output_protocol must be MeasurementProtocol"
            )
        if type(self.model_roles) is not tuple or any(
            type(row) is not ExperimentModelRoleSpec for row in self.model_roles
        ):
            raise TypeError(
                "post-hoc evaluation model_roles must contain ExperimentModelRoleSpec"
            )
        ordered = tuple(
            sorted(self.model_roles, key=lambda row: (row.role, row.member_index))
        )
        keys = tuple((row.role, row.member_index) for row in ordered)
        if len(keys) != len(set(keys)):
            raise ValueError("post-hoc evaluation model role members must be unique")
        if any(not row.usage.affects_evaluation for row in ordered):
            raise ValueError(
                "post-hoc evaluation may bind only evaluation-capable model roles"
            )
        object.__setattr__(self, "model_roles", ordered)
        object.__setattr__(
            self,
            "evaluation_digest",
            canonical_digest(
                {
                    "evaluation_id": self.evaluation_id,
                    "evaluator_id": self.evaluator_id,
                    "evaluator_version": self.evaluator_version,
                    "implementation_digest": self.implementation_digest,
                    "configuration_digest": self.configuration_digest,
                    "source_execution_digest": self.source_execution_digest,
                    "input_cut_digest": self.input_cut.cut_digest,
                    "output_protocol_semantic_digest": (
                        self.output_protocol.semantic_digest
                    ),
                    "model_roles": tuple(row.role_digest for row in ordered),
                }
            ),
        )

    @property
    def evaluation_model_roles_digest(self) -> str:
        return canonical_digest(tuple(row.role_digest for row in self.model_roles))

    def rebind_model_roles(
        self, model_roles: tuple[ExperimentModelRoleSpec, ...]
    ) -> "PostHocEvaluationDefinition":
        """Create a new evaluation identity over the same frozen execution cut."""
        return replace(self, model_roles=model_roles)


@dataclass(frozen=True, slots=True)
class PostHocEvaluationResult:
    evaluation_digest: str
    source_execution_digest: str
    input_cut_digest: str
    output_protocol_semantic_digest: str
    measurement_record_digests: tuple[str, ...]
    evidence_refs: tuple[ArtifactReference, ...] = ()
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("evaluation_digest", self.evaluation_digest),
            ("source_execution_digest", self.source_execution_digest),
            ("input_cut_digest", self.input_cut_digest),
            ("output_protocol_semantic_digest", self.output_protocol_semantic_digest),
        ):
            _sha(value, f"post-hoc evaluation result {name}")
        if type(self.measurement_record_digests) is not tuple or not (
            self.measurement_record_digests
        ):
            raise TypeError(
                "post-hoc evaluation result measurement_record_digests "
                "must be a non-empty tuple"
            )
        for digest in self.measurement_record_digests:
            _sha(digest, "post-hoc evaluation measurement record digest")
        if len(self.measurement_record_digests) != len(
            set(self.measurement_record_digests)
        ):
            raise ValueError(
                "post-hoc evaluation measurement record digests must be unique"
            )
        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError(
                "post-hoc evaluation evidence_refs must contain ArtifactReference"
            )
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest(
                {
                    "evaluation_digest": self.evaluation_digest,
                    "source_execution_digest": self.source_execution_digest,
                    "input_cut_digest": self.input_cut_digest,
                    "output_protocol_semantic_digest": (
                        self.output_protocol_semantic_digest
                    ),
                    "measurement_record_digests": self.measurement_record_digests,
                    "evidence_refs": self.evidence_refs,
                }
            ),
        )


__all__ = ["PostHocEvaluationDefinition", "PostHocEvaluationResult"]
