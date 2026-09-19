from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Protocol, TypeVar, runtime_checkable

from noetrium_platform.capabilities.model.api.project import (
    ModelCapabilityRequirement,
    ProjectModelBinding,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, require_sha256


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value



def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result

@runtime_checkable
class ModelCapabilityInput(Protocol):
    @property
    def schema_id(self) -> str: ...

    def digest(self) -> str: ...


@runtime_checkable
class ModelCapabilityOutput(Protocol):
    @property
    def schema_id(self) -> str: ...

    def digest(self) -> str: ...


InputT = TypeVar("InputT", bound=ModelCapabilityInput)
OutputT = TypeVar("OutputT", bound=ModelCapabilityOutput)


@dataclass(frozen=True, slots=True)
class ModelCapabilityInvocation(Generic[InputT]):
    requirement_digest: str
    capability_id: str
    input_schema_id: str
    invocation_id: str
    payload: InputT
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.requirement_digest, "model capability invocation requirement_digest")
        _text(self.capability_id, "model capability invocation capability_id")
        _text(self.input_schema_id, "model capability invocation input_schema_id")
        _text(self.invocation_id, "model capability invocation invocation_id")
        if not isinstance(self.payload, ModelCapabilityInput):
            raise TypeError("model capability payload must implement ModelCapabilityInput")
        if self.payload.schema_id != self.input_schema_id:
            raise ValueError("model capability input schema does not match invocation schema")
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "requirement_digest": self.requirement_digest,
                    "capability_id": self.capability_id,
                    "input_schema_id": self.input_schema_id,
                    "invocation_id": self.invocation_id,
                    "payload_digest": self.payload.digest(),
                }
            ),
        )

    @classmethod
    def from_requirement(
        cls,
        requirement: ModelCapabilityRequirement,
        invocation_id: str,
        payload: InputT,
    ) -> "ModelCapabilityInvocation[InputT]":
        if not isinstance(requirement, ModelCapabilityRequirement):
            raise TypeError("model capability requirement must be typed")
        if payload.schema_id != requirement.input_schema_id:
            raise ValueError("model capability input schema does not satisfy requirement")
        return cls(
            requirement_digest=requirement.digest(),
            capability_id=requirement.capability_id,
            input_schema_id=requirement.input_schema_id,
            invocation_id=invocation_id,
            payload=payload,
        )


@dataclass(frozen=True, slots=True)
class ModelCapabilityResponse(Generic[OutputT]):
    request_digest: str
    binding_digest: str
    output_schema_id: str
    output: OutputT
    response_digest: str = field(init=False)
    def __post_init__(self) -> None:
        require_sha256(self.request_digest, "model capability response request_digest")
        require_sha256(self.binding_digest, "model capability response binding_digest")
        _text(self.output_schema_id, "model capability response output_schema_id")
        if not isinstance(self.output, ModelCapabilityOutput):
            raise TypeError("model capability output must implement ModelCapabilityOutput")
        if self.output.schema_id != self.output_schema_id:
            raise ValueError("model capability output schema does not match response schema")
        object.__setattr__(
            self,
            "response_digest",
            canonical_digest({
                "request_digest": self.request_digest,
                "binding_digest": self.binding_digest,
                "output_schema_id": self.output_schema_id,
                "output_digest": self.output.digest(),
            }),
        )


@runtime_checkable
class ProjectModelCapabilityClientPort(Protocol[InputT, OutputT]):
    @property
    def binding(self) -> ProjectModelBinding: ...

    @property
    def requirement(self) -> ModelCapabilityRequirement: ...

    def invoke(
        self, request: ModelCapabilityInvocation[InputT]
    ) -> ModelCapabilityResponse[OutputT]: ...


@runtime_checkable
class ProjectModelCapabilityProviderPort(Protocol[InputT, OutputT]):
    @property
    def capability_id(self) -> str: ...

    def bind_capability(
        self, requirement: ModelCapabilityRequirement
    ) -> ProjectModelCapabilityClientPort[InputT, OutputT]: ...


ChunkT = TypeVar("ChunkT", bound=ModelCapabilityOutput)


@dataclass(frozen=True, slots=True)
class ModelCapabilityStreamChunk(Generic[ChunkT]):
    request_digest: str
    binding_digest: str
    sequence_index: int
    chunk_schema_id: str
    payload: ChunkT
    previous_chunk_digest: str | None = None
    chunk_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.request_digest, "model stream chunk request_digest")
        require_sha256(self.binding_digest, "model stream chunk binding_digest")
        if type(self.sequence_index) is not int or self.sequence_index < 0:
            raise ValueError("model stream chunk sequence_index must be non-negative")
        if self.sequence_index == 0:
            if self.previous_chunk_digest is not None:
                raise ValueError("first model stream chunk must not declare previous chunk")
        else:
            if self.previous_chunk_digest is None:
                raise ValueError("non-first model stream chunk requires previous chunk digest")
            require_sha256(self.previous_chunk_digest, "model stream previous chunk digest")
        _text(self.chunk_schema_id, "model stream chunk schema_id")
        if not isinstance(self.payload, ModelCapabilityOutput):
            raise TypeError("model stream chunk payload must implement ModelCapabilityOutput")
        if self.payload.schema_id != self.chunk_schema_id:
            raise ValueError("model stream chunk payload schema drift")
        object.__setattr__(self, "chunk_digest", canonical_digest({
            "request_digest": self.request_digest,
            "binding_digest": self.binding_digest,
            "sequence_index": self.sequence_index,
            "previous_chunk_digest": self.previous_chunk_digest,
            "chunk_schema_id": self.chunk_schema_id,
            "payload_digest": self.payload.digest(),
        }))


class ModelCapabilityStreamDisposition(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ModelCapabilityStreamTerminal(Generic[OutputT]):
    request_digest: str
    binding_digest: str
    disposition: ModelCapabilityStreamDisposition
    chunk_digests: tuple[str, ...]
    final_response: ModelCapabilityResponse[OutputT] | None = None
    reason: str | None = None
    terminal_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.request_digest, "model stream terminal request_digest")
        require_sha256(self.binding_digest, "model stream terminal binding_digest")
        if not isinstance(self.disposition, ModelCapabilityStreamDisposition):
            raise TypeError("model stream terminal disposition must be typed")
        if not isinstance(self.chunk_digests, tuple):
            raise TypeError("model stream terminal chunk_digests must be a tuple")
        for digest in self.chunk_digests:
            require_sha256(digest, "model stream terminal chunk digest")
        if len(set(self.chunk_digests)) != len(self.chunk_digests):
            raise ValueError("model stream terminal chunk digests must be unique")
        if self.disposition is ModelCapabilityStreamDisposition.COMPLETED:
            if not isinstance(self.final_response, ModelCapabilityResponse):
                raise ValueError("completed model stream requires final typed response")
            if self.reason is not None:
                raise ValueError("completed model stream must not carry failure/cancellation reason")
            if self.final_response.request_digest != self.request_digest or self.final_response.binding_digest != self.binding_digest:
                raise ValueError("model stream final response provenance drift")
        else:
            if self.final_response is not None:
                raise ValueError("non-completed model stream must not carry final response")
            _text(self.reason, "model stream terminal reason")
        object.__setattr__(self, "terminal_digest", canonical_digest({
            "request_digest": self.request_digest,
            "binding_digest": self.binding_digest,
            "disposition": self.disposition.value,
            "chunk_digests": self.chunk_digests,
            "final_response_digest": None if self.final_response is None else self.final_response.response_digest,
            "reason": self.reason,
        }))


@runtime_checkable
class ModelCapabilityStreamSession(Protocol[ChunkT, OutputT]):
    @property
    def request_digest(self) -> str: ...

    @property
    def binding_digest(self) -> str: ...

    def next_chunk(self) -> ModelCapabilityStreamChunk[ChunkT] | None: ...
    def terminal(self) -> ModelCapabilityStreamTerminal[OutputT] | None: ...
    def cancel(self, reason: str) -> ModelCapabilityStreamTerminal[OutputT]: ...


@runtime_checkable
class ProjectModelStreamingCapabilityClientPort(Protocol[InputT, ChunkT, OutputT]):
    @property
    def binding(self) -> ProjectModelBinding: ...

    @property
    def requirement(self) -> ModelCapabilityRequirement: ...

    def open_stream(
        self, request: ModelCapabilityInvocation[InputT]
    ) -> ModelCapabilityStreamSession[ChunkT, OutputT]: ...


@runtime_checkable
class ProjectModelStreamingCapabilityProviderPort(Protocol[InputT, ChunkT, OutputT]):
    @property
    def capability_id(self) -> str: ...

    def bind_streaming_capability(
        self, requirement: ModelCapabilityRequirement
    ) -> ProjectModelStreamingCapabilityClientPort[InputT, ChunkT, OutputT]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    texts: tuple[str, ...]
    normalize: bool = False
    schema_id: str = field(init=False, default="model.embedding.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.texts, tuple) or not self.texts:
            raise TypeError("embedding texts must be a non-empty tuple")
        if any(not isinstance(text, str) or not text for text in self.texts):
            raise ValueError("embedding texts must contain non-empty strings")
        if type(self.normalize) is not bool:
            raise TypeError("embedding normalize must be bool")

    def digest(self) -> str:
        return canonical_digest(self)

@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.values, tuple) or not self.values:
            raise TypeError("embedding vector must be a non-empty tuple")
        normalized = tuple(_finite(value, "embedding vector value") for value in self.values)
        object.__setattr__(self, "values", normalized)


@dataclass(frozen=True, slots=True)
class EmbeddingOutput:
    vectors: tuple[EmbeddingVector, ...]
    model_revision: str
    schema_id: str = field(init=False, default="model.embedding.output.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.vectors, tuple) or not self.vectors:
            raise TypeError("embedding output vectors must be a non-empty tuple")
        if any(not isinstance(vector, EmbeddingVector) for vector in self.vectors):
            raise TypeError("embedding output vectors must be typed EmbeddingVector values")
        dimensions = {len(vector.values) for vector in self.vectors}
        if len(dimensions) != 1:
            raise ValueError("embedding output vectors must share one dimension")
        _text(self.model_revision, "embedding output model_revision")

    def digest(self) -> str:
        return canonical_digest(self)

@dataclass(frozen=True, slots=True)
class ScoringCandidate:
    candidate_id: str
    text: str

    def __post_init__(self) -> None:
        _text(self.candidate_id, "scoring candidate_id")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("scoring candidate text must be non-empty")


@dataclass(frozen=True, slots=True)
class ScoringInput:
    query: str
    candidates: tuple[ScoringCandidate, ...]
    schema_id: str = field(init=False, default="model.scoring.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query:
            raise ValueError("scoring query must be non-empty")
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise TypeError("scoring candidates must be a non-empty tuple")
        if any(not isinstance(candidate, ScoringCandidate) for candidate in self.candidates):
            raise TypeError("scoring candidates must be typed ScoringCandidate values")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("scoring candidate ids must be unique")

    def digest(self) -> str:
        return canonical_digest(self)

@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate_id: str
    score: float

    def __post_init__(self) -> None:
        _text(self.candidate_id, "scored candidate_id")
        object.__setattr__(self, "score", _finite(self.score, "scored candidate score"))


@dataclass(frozen=True, slots=True)
class ScoringOutput:
    scores: tuple[ScoredCandidate, ...]
    model_revision: str
    higher_is_better: bool = True
    schema_id: str = field(init=False, default="model.scoring.output.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.scores, tuple) or not self.scores:
            raise TypeError("scoring output scores must be a non-empty tuple")
        if any(not isinstance(score, ScoredCandidate) for score in self.scores):
            raise TypeError("scoring output scores must be typed ScoredCandidate values")
        ids = tuple(score.candidate_id for score in self.scores)
        if len(ids) != len(set(ids)):
            raise ValueError("scoring output candidate ids must be unique")
        _text(self.model_revision, "scoring output model_revision")
        if type(self.higher_is_better) is not bool:
            raise TypeError("scoring higher_is_better must be bool")

    def digest(self) -> str:
        return canonical_digest(self)

@dataclass(frozen=True, slots=True)
class NamedScalar:
    name: str
    value: float

    def __post_init__(self) -> None:
        _text(self.name, "named scalar name")
        object.__setattr__(self, "value", _finite(self.value, "named scalar value"))


@dataclass(frozen=True, slots=True)
class ValueInferenceInput:
    features: tuple[NamedScalar, ...]
    state_id: str | None = None
    schema_id: str = field(init=False, default="model.value.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.features, tuple) or not self.features:
            raise TypeError("value inference features must be a non-empty tuple")
        if any(not isinstance(feature, NamedScalar) for feature in self.features):
            raise TypeError("value inference features must be typed NamedScalar values")
        names = tuple(feature.name for feature in self.features)
        if len(names) != len(set(names)):
            raise ValueError("value inference feature names must be unique")
        if self.state_id is not None:
            _text(self.state_id, "value inference state_id")

    def digest(self) -> str:
        return canonical_digest(self)

@dataclass(frozen=True, slots=True)
class ValueInferenceOutput:
    value: float
    model_revision: str
    uncertainty: float | None = None
    schema_id: str = field(init=False, default="model.value.output.v1")

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _finite(self.value, "value inference value"))
        _text(self.model_revision, "value inference model_revision")
        if self.uncertainty is not None:
            uncertainty = _finite(self.uncertainty, "value inference uncertainty")
            if uncertainty < 0:
                raise ValueError("value inference uncertainty must be non-negative")
            object.__setattr__(self, "uncertainty", uncertainty)

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class StructuredGenerationOutput:
    document: JsonValue
    output_schema_sha256: str
    model_revision: str
    source_response_digest: str
    schema_id: str = field(init=False, default="model.structured-generation.output.v1")

    def __post_init__(self) -> None:
        object.__setattr__(self, "document", freeze_json(self.document))
        require_sha256(self.output_schema_sha256, "structured generation output_schema_sha256")
        _text(self.model_revision, "structured generation model_revision")
        require_sha256(self.source_response_digest, "structured generation source_response_digest")

    def digest(self) -> str:
        return canonical_digest(self)


@runtime_checkable
class StructuredGenerationDecoderPort(Protocol):
    """Decode and validate one completion against the exact requested output schema."""

    def decode_and_validate(self, text: str, *, schema_sha256: str) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class RankingCandidate:
    candidate_id: str
    text: str

    def __post_init__(self) -> None:
        _text(self.candidate_id, "ranking candidate_id")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("ranking candidate text must be non-empty")


@dataclass(frozen=True, slots=True)
class RankingInput:
    query: str
    candidates: tuple[RankingCandidate, ...]
    top_k: int | None = None
    schema_id: str = field(init=False, default="model.ranking.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query:
            raise ValueError("ranking query must be non-empty")
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise TypeError("ranking candidates must be a non-empty tuple")
        if any(not isinstance(candidate, RankingCandidate) for candidate in self.candidates):
            raise TypeError("ranking candidates must be typed RankingCandidate values")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("ranking candidate ids must be unique")
        if self.top_k is not None and (
            type(self.top_k) is not int or self.top_k <= 0 or self.top_k > len(self.candidates)
        ):
            raise ValueError("ranking top_k must be a positive integer within candidate count")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: str
    rank: int
    score: float | None = None

    def __post_init__(self) -> None:
        _text(self.candidate_id, "ranked candidate_id")
        if type(self.rank) is not int or self.rank <= 0:
            raise ValueError("ranked candidate rank must be a positive integer")
        if self.score is not None:
            object.__setattr__(self, "score", _finite(self.score, "ranked candidate score"))


@dataclass(frozen=True, slots=True)
class RankingOutput:
    ranking: tuple[RankedCandidate, ...]
    model_revision: str
    schema_id: str = field(init=False, default="model.ranking.output.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.ranking, tuple) or not self.ranking:
            raise TypeError("ranking output must be a non-empty tuple")
        if any(not isinstance(item, RankedCandidate) for item in self.ranking):
            raise TypeError("ranking output must contain typed RankedCandidate values")
        ids = tuple(item.candidate_id for item in self.ranking)
        ranks = tuple(item.rank for item in self.ranking)
        if len(ids) != len(set(ids)):
            raise ValueError("ranking output candidate ids must be unique")
        if ranks != tuple(range(1, len(ranks) + 1)):
            raise ValueError("ranking output ranks must be contiguous and ordered from one")
        _text(self.model_revision, "ranking output model_revision")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class PolicyInferenceInput:
    state_features: tuple[NamedScalar, ...]
    action_ids: tuple[str, ...]
    schema_id: str = field(init=False, default="model.policy.input.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.state_features, tuple) or not self.state_features:
            raise TypeError("policy state_features must be a non-empty tuple")
        if any(not isinstance(feature, NamedScalar) for feature in self.state_features):
            raise TypeError("policy state_features must be typed NamedScalar values")
        feature_names = tuple(feature.name for feature in self.state_features)
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("policy state feature names must be unique")
        if not isinstance(self.action_ids, tuple) or not self.action_ids:
            raise TypeError("policy action_ids must be a non-empty tuple")
        normalized = tuple(_text(action_id, "policy action_id") for action_id in self.action_ids)
        if len(normalized) != len(set(normalized)):
            raise ValueError("policy action ids must be unique")
        object.__setattr__(self, "action_ids", normalized)

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class PolicyActionProbability:
    action_id: str
    probability: float

    def __post_init__(self) -> None:
        _text(self.action_id, "policy probability action_id")
        probability = _finite(self.probability, "policy action probability")
        if not 0.0 <= probability <= 1.0:
            raise ValueError("policy action probability must be within [0, 1]")
        object.__setattr__(self, "probability", probability)


@dataclass(frozen=True, slots=True)
class PolicyInferenceOutput:
    probabilities: tuple[PolicyActionProbability, ...]
    model_revision: str
    selected_action_id: str | None = None
    schema_id: str = field(init=False, default="model.policy.output.v1")

    def __post_init__(self) -> None:
        if not isinstance(self.probabilities, tuple) or not self.probabilities:
            raise TypeError("policy probabilities must be a non-empty tuple")
        if any(not isinstance(item, PolicyActionProbability) for item in self.probabilities):
            raise TypeError("policy probabilities must contain typed PolicyActionProbability values")
        ids = tuple(item.action_id for item in self.probabilities)
        if len(ids) != len(set(ids)):
            raise ValueError("policy probability action ids must be unique")
        if not math.isclose(sum(item.probability for item in self.probabilities), 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("policy probabilities must sum to one")
        _text(self.model_revision, "policy output model_revision")
        if self.selected_action_id is not None:
            _text(self.selected_action_id, "policy selected_action_id")
            if self.selected_action_id not in ids:
                raise ValueError("policy selected action must appear in the probability distribution")

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = [
    "EmbeddingInput",
    "EmbeddingOutput",
    "EmbeddingVector",
    "ModelCapabilityInput",
    "ModelCapabilityInvocation",
    "ModelCapabilityOutput",
    "ModelCapabilityResponse",
    "NamedScalar",
    "ProjectModelStreamingCapabilityProviderPort",
    "ProjectModelStreamingCapabilityClientPort",
    "ModelCapabilityStreamTerminal",
    "ModelCapabilityStreamSession",
    "ModelCapabilityStreamDisposition",
    "ModelCapabilityStreamChunk",
    "PolicyActionProbability",
    "PolicyInferenceInput",
    "PolicyInferenceOutput",
    "RankedCandidate",
    "RankingCandidate",
    "RankingInput",
    "RankingOutput",
    "ProjectModelCapabilityClientPort",
    "ProjectModelCapabilityProviderPort",
    "ScoredCandidate",
    "ScoringCandidate",
    "ScoringInput",
    "ScoringOutput",
    "StructuredGenerationOutput",
    "StructuredGenerationDecoderPort",
    "ValueInferenceInput",
    "ValueInferenceOutput",
]
