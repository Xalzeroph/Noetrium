from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Mapping

from noetrium_platform.composition.research_execution_content import (
    ResearchExecutionContentAuthorities,
)
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRetention,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    MeasurementValue,
    MeasurementValueKind,
    ResearchStudyDefinition,
    TaskVerifierIsolation,
    TaskVerifierReceipt,
    TaskVerifierRequest,
)

from .cut import (
    GSM8K_BENCHMARK_ID,
    GSM8K_FINAL_ANSWER_MARKER,
    GSM8K_TASK_SCHEMA_ID,
)

GSM8K_VERIFIER_REQUIREMENT_ID = "benchmark.gsm8k.exact-numeric.verifier"

_ANSWER_PHRASE = re.compile(
    r"(?i)(?:the\s+answer\s+is|answer\s*:?)\s*"
    r"(-?\$?[0-9][0-9,]*(?:\.[0-9]+)?)"
)
_NUMBER = re.compile(r"-?\$?[0-9][0-9,]*(?:\.[0-9]+)?")


def normalize_gsm8k_numeric_answer(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("GSM8K numeric answer must be non-empty")
    normalized = value.strip().replace("$", "").replace(",", "")
    try:
        number = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("GSM8K answer is not numeric") from exc
    if not number.is_finite():
        raise ValueError("GSM8K answer must be finite")
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def extract_gsm8k_gold_answer(answer: str) -> str:
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("GSM8K gold answer must be non-empty")
    marker_index = answer.rfind(GSM8K_FINAL_ANSWER_MARKER)
    if marker_index < 0:
        raise ValueError("GSM8K gold answer has no final-answer marker")
    value = answer[marker_index + len(GSM8K_FINAL_ANSWER_MARKER):].strip()
    if not value:
        raise ValueError("GSM8K gold answer has empty final answer")
    return normalize_gsm8k_numeric_answer(value)


def extract_gsm8k_completion_answer(completion: str) -> str:
    """Project model text to the benchmark's final numeric answer."""

    if not isinstance(completion, str) or not completion.strip():
        raise ValueError("GSM8K completion must be non-empty")
    phrase_matches = _ANSWER_PHRASE.findall(completion)
    if phrase_matches:
        raw = phrase_matches[-1]
    else:
        numeric_matches = _NUMBER.findall(completion)
        if not numeric_matches:
            raise ValueError("GSM8K completion contains no numeric final answer")
        raw = numeric_matches[-1]
    return normalize_gsm8k_numeric_answer(raw)


def verify_gsm8k_completion(
    completion: str,
    gold_final_answer: str,
) -> tuple[bool, str]:
    predicted = extract_gsm8k_completion_answer(completion)
    gold = normalize_gsm8k_numeric_answer(gold_final_answer)
    return predicted == gold, predicted


@dataclass(frozen=True, slots=True)
class GSM8KTaskVerifier:
    """Artifact-only GSM8K verifier bound to immutable benchmark gold."""

    content: ResearchExecutionContentAuthorities
    gold_answers: tuple[tuple[str, str], ...]
    identity_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.content) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "GSM8K verifier content must be ResearchExecutionContentAuthorities"
            )
        if type(self.gold_answers) is not tuple or not self.gold_answers:
            raise TypeError("GSM8K verifier gold_answers must be non-empty tuple")
        normalized: list[tuple[str, str]] = []
        for row in self.gold_answers:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError(
                    "GSM8K verifier gold answers must be (task_digest, answer) pairs"
                )
            task_digest, answer = row
            if (
                type(task_digest) is not str
                or len(task_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in task_digest)
            ):
                raise ValueError("GSM8K verifier task_digest must be lowercase SHA-256")
            normalized.append(
                (task_digest, normalize_gsm8k_numeric_answer(answer))
            )
        normalized.sort(key=lambda row: row[0])
        if len({row[0] for row in normalized}) != len(normalized):
            raise ValueError("GSM8K verifier task digests must be unique")
        rows = tuple(normalized)
        object.__setattr__(self, "gold_answers", rows)
        object.__setattr__(
            self,
            "identity_digest",
            canonical_digest(
                {
                    "verifier": "gsm8k.exact-numeric.v1",
                    "requirement_id": GSM8K_VERIFIER_REQUIREMENT_ID,
                    "gold": tuple(
                        (task_digest, canonical_digest({"answer": answer}))
                        for task_digest, answer in rows
                    ),
                }
            ),
        )

    @classmethod
    def from_study(
        cls,
        study: ResearchStudyDefinition,
        *,
        content: ResearchExecutionContentAuthorities,
    ) -> "GSM8KTaskVerifier":
        if type(study) is not ResearchStudyDefinition:
            raise TypeError("GSM8K verifier requires ResearchStudyDefinition")
        if (
            study.benchmark.benchmark_id != GSM8K_BENCHMARK_ID
            or study.benchmark.task_schema_id != GSM8K_TASK_SCHEMA_ID
        ):
            raise ValueError("GSM8K verifier requires GSM8K benchmark task schema")
        rows: list[tuple[str, str]] = []
        for definition in study.benchmark.selected_tasks(study.benchmark_split_id):
            reference = definition.content_reference
            if reference is None:
                raise ValueError(
                    f"GSM8K task {definition.task_id!r} has no immutable content"
                )
            definition.verify_content(content.references, content.artifacts)
            try:
                document = json.loads(content.read(reference).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"GSM8K task {definition.task_id!r} content is not JSON"
                ) from exc
            if not isinstance(document, Mapping):
                raise TypeError(
                    f"GSM8K task {definition.task_id!r} content must be object"
                )
            answer = document.get("answer")
            if not isinstance(answer, str):
                raise TypeError(
                    f"GSM8K task {definition.task_id!r} answer must be text"
                )
            rows.append(
                (
                    definition.task_digest,
                    extract_gsm8k_gold_answer(answer),
                )
            )
        return cls(content, tuple(rows))

    def verify(self, request: TaskVerifierRequest) -> TaskVerifierReceipt:
        if type(request) is not TaskVerifierRequest:
            raise TypeError("GSM8K verifier requires TaskVerifierRequest")
        if request.verifier_requirement_id != GSM8K_VERIFIER_REQUIREMENT_ID:
            raise ValueError("GSM8K verifier requirement identity drifted")
        if request.verifier_isolation is not TaskVerifierIsolation.SEPARATE:
            raise ValueError("GSM8K verifier requires separate verifier isolation")
        gold = dict(self.gold_answers).get(request.task_digest)
        if gold is None:
            raise KeyError(
                f"GSM8K verifier has no immutable gold for {request.task_digest}"
            )
        completion_artifacts = tuple(
            row for row in request.artifacts
            if row.declaration.artifact_id == "completion"
        )
        if len(completion_artifacts) != 1:
            raise ValueError("GSM8K verifier requires exactly one completion artifact")
        completion_artifact = completion_artifacts[0]
        try:
            completion = json.loads(
                self.content.read(completion_artifact.reference).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("GSM8K completion artifact is not JSON") from exc
        if not isinstance(completion, str) or not completion.strip():
            raise TypeError("GSM8K completion artifact must contain text")

        correct, predicted = verify_gsm8k_completion(completion, gold)
        owned = tuple(
            definition
            for definition in request.measurement_protocol.definitions
            if definition.semantic_kind == "exact_numeric_answer_success"
        )
        if len(owned) != 1:
            raise ValueError(
                "GSM8K verifier requires exactly one exact-numeric-answer measurement"
            )
        measurement_definition = owned[0]
        if measurement_definition.value_kind is not MeasurementValueKind.SCALAR:
            raise TypeError("GSM8K exact-answer measurement must be scalar")
        measurement = request.measurement(
            measurement_definition.measurement_id,
            MeasurementValue(
                MeasurementValueKind.SCALAR,
                scalar=1.0 if correct else 0.0,
            ),
            producer_id=GSM8K_VERIFIER_REQUIREMENT_ID,
            producer_revision_digest=self.identity_digest,
            logical_time=(
                f"verifier:{request.assignment_digest}:"
                f"{measurement_definition.measurement_id}"
            ),
            lineage_refs=(completion_artifact.reference,),
        )

        evidence = self.content.publish(
            reference_id=f"verifier:gsm8k:{request.request_digest}",
            scope=ScopeIdentity(ScopeKind.RUN, request.run_id),
            payload=canonical_bytes(
                {
                    "schema": "gsm8k.verifier-evidence.v1",
                    "request_digest": request.request_digest,
                    "task_digest": request.task_digest,
                    "completion_artifact_id": completion_artifact.reference.artifact_id,
                    "predicted": predicted,
                    "gold": gold,
                    "correct": correct,
                }
            ),
            media_type="application/json",
            kind=ArtifactKind.SCIENTIFIC,
            retention=ArtifactRetention.RUN,
            producer_component_id=GSM8K_VERIFIER_REQUIREMENT_ID,
            metadata={
                "task_digest": request.task_digest,
                "measurement_id": measurement_definition.measurement_id,
            },
        )
        return TaskVerifierReceipt(
            request,
            (measurement,),
            (evidence,),
        )


__all__ = [
    "GSM8KTaskVerifier",
    "GSM8K_VERIFIER_REQUIREMENT_ID",
    "extract_gsm8k_completion_answer",
    "extract_gsm8k_gold_answer",
    "normalize_gsm8k_numeric_answer",
    "verify_gsm8k_completion",
]
