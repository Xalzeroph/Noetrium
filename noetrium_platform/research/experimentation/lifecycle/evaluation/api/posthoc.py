"""Post-hoc evaluation identity and declarative scoring semantics.

Evaluation owns scoring/reduction policy. Study owns experimental design and typed
measurements; the two are connected by immutable Measurement cuts and protocols,
not by sharing lifecycle authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
import math

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.research.execution.api import ArtifactReference
from noetrium_platform.research.experimentation.lifecycle.experiment.api import (
    ExperimentModelRoleSpec,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.analysis import (
    MeasurementCut,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.measurement import (
    MeasurementProtocol,
)

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


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


class EvaluationScoreState(StrEnum):
    """Whether a scorer produced a value for one evaluation epoch."""

    SCORED = "scored"
    UNSCORED = "unscored"


@dataclass(frozen=True, slots=True)
class EvaluationScore:
    """One immutable scorer output with auditable provenance.

    A score is never represented by a bare scalar.  UNSCORED preserves the
    reason/explanation/evidence while keeping absence distinct from numeric zero.
    """

    score_id: str
    state: EvaluationScoreState
    value: JsonValue | None = None
    reason: str | None = None
    answer: str | None = None
    explanation: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    evidence_refs: tuple[ArtifactReference, ...] = ()
    score_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.score_id, "evaluation score score_id")
        if not isinstance(self.state, EvaluationScoreState):
            raise TypeError("evaluation score state must be EvaluationScoreState")

        if self.state is EvaluationScoreState.SCORED:
            if self.value is None:
                raise ValueError("scored evaluation score requires value")
            if self.reason is not None:
                raise ValueError("scored evaluation score cannot carry abnormal reason")
            object.__setattr__(self, "value", freeze_json(self.value))
        else:
            if self.value is not None:
                raise ValueError("unscored evaluation score cannot carry value")
            _text(self.reason, "unscored evaluation score reason")

        for field_name, value in (
            ("answer", self.answer),
            ("explanation", self.explanation),
        ):
            if value is not None:
                _text(value, f"evaluation score {field_name}")

        frozen_metadata = freeze_json(self.metadata)
        if not isinstance(frozen_metadata, Mapping):
            raise TypeError("evaluation score metadata must be a mapping")
        object.__setattr__(self, "metadata", frozen_metadata)

        if type(self.evidence_refs) is not tuple or any(
            type(row) is not ArtifactReference for row in self.evidence_refs
        ):
            raise TypeError(
                "evaluation score evidence_refs must contain ArtifactReference"
            )
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evaluation score evidence_refs must be unique")

        object.__setattr__(
            self,
            "score_digest",
            canonical_digest(
                {
                    "score_id": self.score_id,
                    "state": self.state.value,
                    "value": self.value,
                    "reason": self.reason,
                    "answer": self.answer,
                    "explanation": self.explanation,
                    "metadata": frozen_metadata,
                    "evidence_refs": self.evidence_refs,
                }
            ),
        )

    @classmethod
    def scored(
        cls,
        score_id: str,
        value: JsonValue,
        *,
        answer: str | None = None,
        explanation: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
        evidence_refs: tuple[ArtifactReference, ...] = (),
    ) -> "EvaluationScore":
        return cls(
            score_id=score_id,
            state=EvaluationScoreState.SCORED,
            value=value,
            answer=answer,
            explanation=explanation,
            metadata={} if metadata is None else metadata,
            evidence_refs=evidence_refs,
        )

    @classmethod
    def unscored(
        cls,
        score_id: str,
        *,
        reason: str,
        answer: str | None = None,
        explanation: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
        evidence_refs: tuple[ArtifactReference, ...] = (),
    ) -> "EvaluationScore":
        return cls(
            score_id=score_id,
            state=EvaluationScoreState.UNSCORED,
            reason=reason,
            answer=answer,
            explanation=explanation,
            metadata={} if metadata is None else metadata,
            evidence_refs=evidence_refs,
        )


class EvaluationScoreView(StrEnum):
    """Which score cut a metric consumes when repeated epochs are present."""

    REDUCED = "reduced"
    UNREDUCED = "unreduced"


class EvaluationReducerKind(StrEnum):
    """Built-in reducers; custom reducers use EvaluationReducerSpec directly."""

    MEAN = "mean"
    MEDIAN = "median"
    MODE = "mode"
    MAJORITY = "majority"
    MAX = "max"
    PASS_AT_K = "pass_at_k"
    PASS_K = "pass_k"
    AT_LEAST_K = "at_least_k"
    COLLECT = "collect"


_K_REDUCERS = frozenset(
    {
        EvaluationReducerKind.PASS_AT_K,
        EvaluationReducerKind.PASS_K,
        EvaluationReducerKind.AT_LEAST_K,
    }
)


@dataclass(frozen=True, slots=True)
class EvaluationReducerSpec:
    """Immutable identity for one score-reduction operation.

    operation_id is intentionally open so paper-specific reducers remain downstream
    programmable operations rather than new platform enum members.
    """

    reducer_id: str
    operation_id: str
    implementation_digest: str
    configuration: Mapping[str, JsonValue] = field(default_factory=dict)
    reducer_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.reducer_id, "evaluation reducer reducer_id")
        _text(self.operation_id, "evaluation reducer operation_id")
        _sha(self.implementation_digest, "evaluation reducer implementation_digest")
        frozen = freeze_json(self.configuration)
        if not isinstance(frozen, Mapping):
            raise TypeError("evaluation reducer configuration must be a mapping")
        object.__setattr__(self, "configuration", frozen)
        object.__setattr__(
            self,
            "reducer_digest",
            canonical_digest(
                {
                    "reducer_id": self.reducer_id,
                    "operation_id": self.operation_id,
                    "implementation_digest": self.implementation_digest,
                    "configuration": frozen,
                }
            ),
        )

    @classmethod
    def builtin(
        cls,
        reducer_id: str,
        kind: EvaluationReducerKind,
        *,
        k: int | None = None,
        threshold: float = 1.0,
    ) -> "EvaluationReducerSpec":
        if not isinstance(kind, EvaluationReducerKind):
            raise TypeError("evaluation reducer kind must be EvaluationReducerKind")
        configuration: JsonObject = {}
        if kind in _K_REDUCERS:
            if type(k) is not int or k <= 0:
                raise ValueError(f"{kind.value} requires positive integer k")
            configuration = {
                "k": k,
                "threshold": _finite(threshold, f"{kind.value} threshold"),
            }
        elif k is not None or threshold != 1.0:
            raise ValueError(
                f"{kind.value} does not accept k/threshold configuration"
            )
        return cls(
            reducer_id=reducer_id,
            operation_id=f"evaluation.reducer.{kind.value}",
            implementation_digest=canonical_digest(
                {
                    "operation": f"evaluation.reducer.{kind.value}",
                    "implementation_revision": 1,
                }
            ),
            configuration=configuration,
        )


@dataclass(frozen=True, slots=True)
class EvaluationMetricSpec:
    """Metric computation over either raw epoch scores or a named reduced view."""

    metric_id: str
    score_measurement_id: str
    score_view: EvaluationScoreView
    operation_id: str
    implementation_digest: str
    reducer_id: str | None = None
    configuration: Mapping[str, JsonValue] = field(default_factory=dict)
    metric_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.metric_id, "evaluation metric metric_id")
        _text(self.score_measurement_id, "evaluation metric score_measurement_id")
        if not isinstance(self.score_view, EvaluationScoreView):
            raise TypeError("evaluation metric score_view must be EvaluationScoreView")
        _text(self.operation_id, "evaluation metric operation_id")
        _sha(self.implementation_digest, "evaluation metric implementation_digest")
        if self.score_view is EvaluationScoreView.REDUCED:
            if self.reducer_id is None:
                raise ValueError("reduced evaluation metric requires reducer_id")
            _text(self.reducer_id, "evaluation metric reducer_id")
        elif self.reducer_id is not None:
            raise ValueError("unreduced evaluation metric cannot bind reducer_id")
        frozen = freeze_json(self.configuration)
        if not isinstance(frozen, Mapping):
            raise TypeError("evaluation metric configuration must be a mapping")
        object.__setattr__(self, "configuration", frozen)
        object.__setattr__(
            self,
            "metric_digest",
            canonical_digest(
                {
                    "metric_id": self.metric_id,
                    "score_measurement_id": self.score_measurement_id,
                    "score_view": self.score_view.value,
                    "operation_id": self.operation_id,
                    "implementation_digest": self.implementation_digest,
                    "reducer_id": self.reducer_id,
                    "configuration": frozen,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class EvaluationScoringProtocol:
    """Frozen scorer -> reducer-view -> metric -> headline contract."""

    protocol_id: str
    reducers: tuple[EvaluationReducerSpec, ...]
    metrics: tuple[EvaluationMetricSpec, ...]
    headline_metric_id: str
    semantic_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.protocol_id, "evaluation scoring protocol_id")
        if type(self.reducers) is not tuple or any(
            type(row) is not EvaluationReducerSpec for row in self.reducers
        ):
            raise TypeError(
                "evaluation scoring reducers must contain EvaluationReducerSpec"
            )
        if type(self.metrics) is not tuple or not self.metrics or any(
            type(row) is not EvaluationMetricSpec for row in self.metrics
        ):
            raise TypeError(
                "evaluation scoring metrics must be a non-empty tuple of EvaluationMetricSpec"
            )
        reducers = tuple(sorted(self.reducers, key=lambda row: row.reducer_id))
        metrics = tuple(sorted(self.metrics, key=lambda row: row.metric_id))
        reducer_ids = tuple(row.reducer_id for row in reducers)
        metric_ids = tuple(row.metric_id for row in metrics)
        if len(reducer_ids) != len(set(reducer_ids)):
            raise ValueError("evaluation scoring reducer ids must be unique")
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("evaluation scoring metric ids must be unique")
        known_reducers = set(reducer_ids)
        referenced = {
            row.reducer_id for row in metrics if row.reducer_id is not None
        }
        unknown = referenced - known_reducers
        if unknown:
            raise ValueError(
                f"evaluation scoring metrics reference unknown reducers: {sorted(unknown)}"
            )
        unused = known_reducers - referenced
        if unused:
            raise ValueError(
                f"evaluation scoring protocol contains unused reducers: {sorted(unused)}"
            )
        _text(self.headline_metric_id, "evaluation scoring headline_metric_id")
        if self.headline_metric_id not in set(metric_ids):
            raise ValueError("evaluation scoring headline metric is not declared")
        object.__setattr__(self, "reducers", reducers)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(
            self,
            "semantic_digest",
            canonical_digest(
                {
                    "protocol_id": self.protocol_id,
                    "reducers": tuple(row.reducer_digest for row in reducers),
                    "metrics": tuple(row.metric_digest for row in metrics),
                    "headline_metric_id": self.headline_metric_id,
                }
            ),
        )

    def reducer(self, reducer_id: str) -> EvaluationReducerSpec:
        matches = tuple(row for row in self.reducers if row.reducer_id == reducer_id)
        if len(matches) != 1:
            raise KeyError(f"evaluation scoring protocol has no unique reducer {reducer_id!r}")
        return matches[0]


class EvaluationReductionState(StrEnum):
    SCORED = "scored"
    UNSCORED = "unscored"


@dataclass(frozen=True, slots=True)
class EvaluationReductionResult:
    reducer_digest: str
    state: EvaluationReductionState
    source_score_digests: tuple[str, ...]
    scored_source_count: int
    value: JsonValue | None = None
    reason: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.reducer_digest, "evaluation reduction reducer_digest")
        if not isinstance(self.state, EvaluationReductionState):
            raise TypeError("evaluation reduction state must be EvaluationReductionState")
        if type(self.source_score_digests) is not tuple or not self.source_score_digests:
            raise ValueError(
                "evaluation reduction source_score_digests must be a non-empty tuple"
            )
        for digest in self.source_score_digests:
            _sha(digest, "evaluation reduction source score digest")
        if len(self.source_score_digests) != len(set(self.source_score_digests)):
            raise ValueError("evaluation reduction source score digests must be unique")
        if (
            type(self.scored_source_count) is not int
            or self.scored_source_count < 0
            or self.scored_source_count > len(self.source_score_digests)
        ):
            raise ValueError(
                "evaluation reduction scored_source_count is outside source cut"
            )
        if self.state is EvaluationReductionState.SCORED:
            if self.value is None:
                raise ValueError("scored evaluation reduction requires value")
            if self.reason is not None:
                raise ValueError("scored evaluation reduction cannot carry reason")
            if self.scored_source_count == 0:
                raise ValueError("scored evaluation reduction requires scored source")
            object.__setattr__(self, "value", freeze_json(self.value))
        else:
            if self.value is not None:
                raise ValueError("unscored evaluation reduction cannot carry value")
            _text(self.reason, "unscored evaluation reduction reason")

        frozen_metadata = freeze_json(self.metadata)
        if not isinstance(frozen_metadata, Mapping):
            raise TypeError("evaluation reduction metadata must be a mapping")
        object.__setattr__(self, "metadata", frozen_metadata)
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest(
                {
                    "reducer_digest": self.reducer_digest,
                    "state": self.state.value,
                    "source_score_digests": self.source_score_digests,
                    "scored_source_count": self.scored_source_count,
                    "value": self.value,
                    "reason": self.reason,
                    "metadata": frozen_metadata,
                }
            ),
        )

    @property
    def source_count(self) -> int:
        return len(self.source_score_digests)


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
    scoring_protocol: EvaluationScoringProtocol
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
        if type(self.scoring_protocol) is not EvaluationScoringProtocol:
            raise TypeError(
                "post-hoc evaluation scoring_protocol must be EvaluationScoringProtocol"
            )
        for metric in self.scoring_protocol.metrics:
            try:
                self.output_protocol.definition(metric.score_measurement_id)
            except KeyError as exc:
                raise ValueError(
                    "evaluation scoring metric references measurement absent from output protocol: "
                    f"{metric.score_measurement_id}"
                ) from exc
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
                    "scoring_protocol_semantic_digest": (
                        self.scoring_protocol.semantic_digest
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
    scoring_protocol_semantic_digest: str
    measurement_record_digests: tuple[str, ...]
    evidence_refs: tuple[ArtifactReference, ...] = ()
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("evaluation_digest", self.evaluation_digest),
            ("source_execution_digest", self.source_execution_digest),
            ("input_cut_digest", self.input_cut_digest),
            ("output_protocol_semantic_digest", self.output_protocol_semantic_digest),
            ("scoring_protocol_semantic_digest", self.scoring_protocol_semantic_digest),
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
                    "scoring_protocol_semantic_digest": (
                        self.scoring_protocol_semantic_digest
                    ),
                    "measurement_record_digests": self.measurement_record_digests,
                    "evidence_refs": self.evidence_refs,
                }
            ),
        )


__all__ = [
    "EvaluationMetricSpec",
    "EvaluationScore",
    "EvaluationScoreState",
    "EvaluationReducerKind",
    "EvaluationReducerSpec",
    "EvaluationReductionResult",
    "EvaluationReductionState",
    "EvaluationScoreView",
    "EvaluationScoringProtocol",
    "PostHocEvaluationDefinition",
    "PostHocEvaluationResult",
]
