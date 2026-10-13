"""Post-hoc evaluation identity over frozen execution/evidence cuts.

Evaluation is separate from original execution identity. Rebinding an
evaluation/grader model creates a new evaluation identity while preserving the
source execution digest.
"""
from __future__ import annotations


from dataclasses import dataclass, field

from noetrium_platform.research.execution.api import ArtifactReference
from noetrium_platform.foundation.kernel.kernel import canonical_digest

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


__all__ = ["PostHocEvaluationResult"]
