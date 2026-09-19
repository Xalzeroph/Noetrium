from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    MemoryConcern,
    MemoryProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import VIDEOAGENT_REFERENCE_FIDELITY
from .source import VIDEOAGENT_AUDITED_COMMIT


_REQUIRED_MEMORY_ARTIFACTS = VIDEOAGENT_REFERENCE_FIDELITY.preprocessing_artifacts


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _blob_payload(ref: ArtifactBlobRef) -> JsonObject:
    return {
        "content_sha256": ref.content_sha256,
        "size_bytes": ref.size_bytes,
        "media_type": ref.media_type,
    }


def _blob_ref(value: object, field_name: str) -> ArtifactBlobRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return ArtifactBlobRef(
        content_sha256=_text(
            value.get("content_sha256"),
            f"{field_name}.content_sha256",
        ),
        size_bytes=value.get("size_bytes"),
        media_type=_text(
            value.get("media_type"),
            f"{field_name}.media_type",
        ),
    )


@dataclass(frozen=True, slots=True)
class VideoAgentMemoryBundle:
    video_id: str
    segment_count: int
    artifacts: tuple[tuple[str, ArtifactBlobRef], ...]
    use_reid: bool = True
    bundle_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "video_id",
            _text(self.video_id, "VideoAgent video_id"),
        )
        if type(self.segment_count) is not int or self.segment_count < 1:
            raise ValueError("VideoAgent segment_count must be positive")
        if type(self.use_reid) is not bool:
            raise TypeError("VideoAgent use_reid must be boolean")
        if type(self.artifacts) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or not isinstance(row[1], ArtifactBlobRef)
            for row in self.artifacts
        ):
            raise TypeError(
                "VideoAgent artifacts must be (name, ArtifactBlobRef) tuples"
            )
        names = tuple(name for name, _ in self.artifacts)
        if names != tuple(sorted(names)):
            raise ValueError("VideoAgent artifact rows must be sorted")
        if len(names) != len(set(names)):
            raise ValueError("VideoAgent artifact names must be unique")
        missing = tuple(
            name for name in _REQUIRED_MEMORY_ARTIFACTS
            if name not in set(names)
        )
        if missing:
            raise ValueError(
                f"VideoAgent memory bundle missing artifacts: {missing}"
            )
        object.__setattr__(
            self,
            "bundle_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    @property
    def artifact_refs(self) -> tuple[str, ...]:
        return tuple(
            f"sha256:{ref.content_sha256}"
            for _, ref in self.artifacts
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "video_id": self.video_id,
            "segment_count": self.segment_count,
            "use_reid": self.use_reid,
            "artifacts": tuple(
                {
                    "name": name,
                    "blob": _blob_payload(ref),
                }
                for name, ref in self.artifacts
            ),
        }
        if include_digest:
            payload["bundle_digest"] = self.bundle_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "VideoAgentMemoryBundle":
        if not isinstance(value, Mapping):
            raise TypeError("VideoAgent memory bundle must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("VideoAgent memory bundle must decode to object")
        rows = decoded.get("artifacts", ())
        if isinstance(rows, (str, bytes, bytearray)) or not isinstance(
            rows,
            Sequence,
        ):
            raise TypeError("VideoAgent memory artifacts must be a sequence")
        artifacts: list[tuple[str, ArtifactBlobRef]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise TypeError("VideoAgent memory artifact row must be object")
            name = _text(row.get("name"), "VideoAgent artifact name")
            artifacts.append(
                (
                    name,
                    _blob_ref(
                        row.get("blob"),
                        f"VideoAgent artifact {name}",
                    ),
                )
            )
        bundle = cls(
            video_id=_text(decoded.get("video_id"), "VideoAgent video_id"),
            segment_count=decoded.get("segment_count"),
            artifacts=tuple(sorted(artifacts, key=lambda item: item[0])),
            use_reid=decoded.get("use_reid", True),
        )
        supplied = decoded.get("bundle_digest")
        if supplied is not None and require_sha256(
            supplied,
            "VideoAgent bundle_digest",
        ) != bundle.bundle_digest:
            raise ValueError("VideoAgent memory bundle digest mismatch")
        return bundle


@dataclass(frozen=True, slots=True)
class VideoAgentCaption:
    segment_id: int
    caption: str

    def __post_init__(self) -> None:
        if type(self.segment_id) is not int or self.segment_id < 0:
            raise ValueError("VideoAgent caption segment_id must be non-negative")
        object.__setattr__(
            self,
            "caption",
            _text(self.caption, "VideoAgent caption"),
        )

    def payload(self) -> JsonObject:
        return {
            "segment_id": self.segment_id,
            "caption": self.caption,
        }


@dataclass(frozen=True, slots=True)
class VideoAgentSegmentScoreTable:
    segment_ids: tuple[int, ...]
    textual_scores: tuple[float, ...]
    visual_scores: tuple[float, ...]
    receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.segment_ids) is not tuple or any(
            type(value) is not int or value < 0
            for value in self.segment_ids
        ):
            raise TypeError(
                "VideoAgent segment_ids must be non-negative integer tuple"
            )
        if len(self.segment_ids) != len(set(self.segment_ids)):
            raise ValueError("VideoAgent segment_ids must be unique")
        if (
            type(self.textual_scores) is not tuple
            or type(self.visual_scores) is not tuple
            or len(self.textual_scores) != len(self.segment_ids)
            or len(self.visual_scores) != len(self.segment_ids)
        ):
            raise ValueError(
                "VideoAgent localization score tables must align"
            )
        textual = tuple(
            _number(value, "VideoAgent textual score")
            for value in self.textual_scores
        )
        visual = tuple(
            _number(value, "VideoAgent visual score")
            for value in self.visual_scores
        )
        object.__setattr__(self, "textual_scores", textual)
        object.__setattr__(self, "visual_scores", visual)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "segment_ids": self.segment_ids,
                "textual_scores": textual,
                "visual_scores": visual,
                "receipt": thaw_json(self.receipt),
            }),
        )


@runtime_checkable
class VideoAgentMemoryIndexPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def captions(
        self,
        bundle: VideoAgentMemoryBundle,
        start_segment: int,
        end_segment: int,
    ) -> tuple[VideoAgentCaption, ...]: ...

    def segment_scores(
        self,
        bundle: VideoAgentMemoryBundle,
        description: str,
    ) -> VideoAgentSegmentScoreTable: ...

    def database_query(
        self,
        bundle: VideoAgentMemoryBundle,
        program: str,
    ) -> JsonValue: ...

    def retrieve_candidate_objects(
        self,
        bundle: VideoAgentMemoryBundle,
        description: str,
    ) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class VideoAgentMemoryBinding:
    index: VideoAgentMemoryIndexPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.index, VideoAgentMemoryIndexPort):
            raise TypeError(
                "VideoAgent memory binding requires VideoAgentMemoryIndexPort"
            )
        identity = require_sha256(
            self.index.identity_digest,
            "VideoAgent memory index identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": VIDEOAGENT_AUDITED_COMMIT,
                "index_identity_digest": identity,
                "implementation_revision": 1,
            }),
        )


def videoagent_memory_initial_data(
    bundle: VideoAgentMemoryBundle,
) -> JsonObject:
    if not isinstance(bundle, VideoAgentMemoryBundle):
        raise TypeError(
            "VideoAgent memory initial data requires VideoAgentMemoryBundle"
        )
    return {
        "source_commit": VIDEOAGENT_AUDITED_COMMIT,
        "bundle": bundle.payload(),
        "sequence": 0,
        "result": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("VideoAgent memory data must be object")
    if decoded.get("source_commit") != VIDEOAGENT_AUDITED_COMMIT:
        raise ValueError("VideoAgent source identity drifted")
    return decoded


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("VideoAgent memory payload must be object")
    event = decoded.get("event")
    if not isinstance(event, dict):
        raise TypeError("VideoAgent memory requires event envelope")
    return event


def _event_payload(event: Mapping[str, object]) -> dict[str, object]:
    value = event.get("payload", {})
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("VideoAgent memory event payload must be object")
    return decoded


def _sequence(data: Mapping[str, object]) -> int:
    value = data.get("sequence", 0)
    if type(value) is not int or value < 0:
        raise ValueError("VideoAgent memory sequence is invalid")
    return value


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, VideoAgentMemoryBinding):
        raise TypeError(
            "VideoAgent memory dispatch requires VideoAgentMemoryBinding"
        )
    data = _data(request)
    event = _payload(request)
    kind = _text(event.get("kind"), "VideoAgent memory event kind")
    payload = _event_payload(event)
    bundle = VideoAgentMemoryBundle.from_payload(data.get("bundle"))
    sequence = _sequence(data) + 1

    if kind == "videoagent.memory.caption-range":
        start = payload.get("start_segment")
        end = payload.get("end_segment")
        if type(start) is not int or type(end) is not int:
            raise TypeError(
                "VideoAgent caption range requires integer segment ids"
            )
        bounded_start = max(start, 0)
        bounded_end = min(end, bundle.segment_count - 1)
        invalid = bounded_start > bounded_end
        rows = (
            ()
            if invalid
            else binding.index.captions(
                bundle,
                bounded_start,
                bounded_end,
            )
        )
        if any(not isinstance(row, VideoAgentCaption) for row in rows):
            raise TypeError(
                "VideoAgent caption port must return VideoAgentCaption rows"
            )
        unknown = tuple(
            row.segment_id
            for row in rows
            if row.segment_id < bounded_start
            or row.segment_id > bounded_end
        )
        if unknown:
            raise ValueError(
                f"VideoAgent caption port returned out-of-range ids: {unknown}"
            )
        result = {
            "segment_count": bundle.segment_count,
            "requested_start": start,
            "requested_end": end,
            "bounded_start": bounded_start,
            "bounded_end": bounded_end,
            "invalid_range": invalid,
            "captions": tuple(row.payload() for row in rows),
            "declared_max_caption_count": (
                VIDEOAGENT_REFERENCE_FIDELITY.caption_declared_max_count
            ),
            "source_enforces_declared_limit": False,
        }

    elif kind == "videoagent.memory.segment-localize":
        description = _text(
            payload.get("description"),
            "VideoAgent localization description",
        )
        table = binding.index.segment_scores(bundle, description)
        if not isinstance(table, VideoAgentSegmentScoreTable):
            raise TypeError(
                "VideoAgent segment-score port returned invalid result"
            )
        unknown = tuple(
            value
            for value in table.segment_ids
            if value >= bundle.segment_count
        )
        if unknown:
            raise ValueError(
                f"VideoAgent localization returned unknown segments: {unknown}"
            )
        visual_weight = (
            VIDEOAGENT_REFERENCE_FIDELITY.segment_visual_score_weight
        )
        textual_weight = (
            VIDEOAGENT_REFERENCE_FIDELITY.segment_textual_score_weight
        )
        scored = tuple(
            (
                segment_id,
                visual_weight * visual
                + textual_weight * textual,
                textual,
                visual,
            )
            for segment_id, textual, visual in zip(
                table.segment_ids,
                table.textual_scores,
                table.visual_scores,
            )
        )
        ranked = tuple(
            sorted(scored, key=lambda row: (-row[1], row[0]))
        )
        selected = ranked[
            : VIDEOAGENT_REFERENCE_FIDELITY.segment_localization_top_k
        ]
        captions = binding.index.captions(
            bundle,
            0,
            bundle.segment_count - 1,
        )
        caption_by_id = {row.segment_id: row.caption for row in captions}
        result = {
            "description": description,
            "visual_weight": visual_weight,
            "textual_weight": textual_weight,
            "top_k": VIDEOAGENT_REFERENCE_FIDELITY.segment_localization_top_k,
            "segment_ids": tuple(row[0] for row in selected),
            "ensemble_scores": tuple(row[1] for row in selected),
            "captions": tuple(
                {
                    "segment_id": row[0],
                    "caption": caption_by_id.get(row[0], ""),
                }
                for row in selected
            ),
            "score_table_digest": table.result_digest,
            "score_receipt": thaw_json(table.receipt),
        }

    elif kind == "videoagent.memory.object-database":
        program = _text(
            payload.get("program"),
            "VideoAgent object-memory database program",
        )
        value = binding.index.database_query(bundle, program)
        result = {
            "program": program,
            "value": thaw_json(value),
            "query_digest": canonical_digest({
                "program": program,
                "value": thaw_json(value),
            }),
        }

    elif kind == "videoagent.memory.object-retrieve":
        description = _text(
            payload.get("description"),
            "VideoAgent object retrieval description",
        )
        value = binding.index.retrieve_candidate_objects(
            bundle,
            description,
        )
        result = {
            "description": description,
            "value": thaw_json(value),
            "query_digest": canonical_digest({
                "description": description,
                "value": thaw_json(value),
            }),
        }

    else:
        raise ValueError(
            f"unsupported VideoAgent memory event: {kind}"
        )

    query_digest = canonical_digest({
        "bundle_digest": bundle.bundle_digest,
        "sequence": sequence,
        "kind": kind,
        "payload": payload,
        "result": result,
    })
    result = {
        **result,
        "bundle_digest": bundle.bundle_digest,
        "query_sequence": sequence,
        "query_digest": query_digest,
    }
    return ProgramNodeResult(
        value=result,
        state_update={
            "sequence": sequence,
            "result": result,
        },
        events=({
            "type": "videoagent_memory_query",
            "kind": kind,
            "bundle_digest": bundle.bundle_digest,
            "query_sequence": sequence,
            "query_digest": query_digest,
        },),
        artifact_refs=bundle.artifact_refs,
    )


def build_videoagent_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="videoagent.structured-video-memory",
            version=VIDEOAGENT_AUDITED_COMMIT[:12],
            state_schema="videoagent.structured-video-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "videoagent.memory.dispatch",
            configuration={
                "source_commit": VIDEOAGENT_AUDITED_COMMIT,
                "memory_concerns": (
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.INDEX.value,
                ),
                "segment_seconds": (
                    VIDEOAGENT_REFERENCE_FIDELITY.segment_seconds
                ),
                "segment_localization_top_k": (
                    VIDEOAGENT_REFERENCE_FIDELITY
                    .segment_localization_top_k
                ),
                "segment_score_weights": (
                    VIDEOAGENT_REFERENCE_FIDELITY
                    .segment_visual_score_weight,
                    VIDEOAGENT_REFERENCE_FIDELITY
                    .segment_textual_score_weight,
                ),
                "bundle_storage": "artifact-content-addressed",
            },
            next_node="dispatch",
        )
        .build()
    )


VIDEOAGENT_MEMORY_PROGRAM = build_videoagent_memory_program()


def videoagent_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "videoagent.memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "videoagent.memory.dispatch",
                "source_commit": VIDEOAGENT_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def videoagent_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="videoagent.structured-video-memory",
        program=VIDEOAGENT_MEMORY_PROGRAM,
        operations=videoagent_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": VIDEOAGENT_AUDITED_COMMIT,
            "segment_seconds": (
                VIDEOAGENT_REFERENCE_FIDELITY.segment_seconds
            ),
            "localization_weights": (
                VIDEOAGENT_REFERENCE_FIDELITY
                .segment_visual_score_weight,
                VIDEOAGENT_REFERENCE_FIDELITY
                .segment_textual_score_weight,
            ),
        },
    )


__all__ = [
    "VIDEOAGENT_MEMORY_PROGRAM",
    "VideoAgentCaption",
    "VideoAgentMemoryBinding",
    "VideoAgentMemoryBundle",
    "VideoAgentMemoryIndexPort",
    "VideoAgentSegmentScoreTable",
    "build_videoagent_memory_program",
    "videoagent_memory_host",
    "videoagent_memory_initial_data",
    "videoagent_memory_operations",
]
