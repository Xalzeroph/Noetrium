from __future__ import annotations

from collections.abc import Mapping
from typing import Iterable

from noetrium_platform.capabilities.model.api import MultimodalPart
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest, freeze_json

from ..api.cognition import AgentObservation


class AgentMultimodalObservationProjector:
    """Projects arbitrary content-addressed parts into an agent observation.

    This assembler does not interpret a modality. Interpretation belongs to a
    method/provider selected by the project; the observation retains the raw
    part identity and provenance for replay.
    """

    def project(
        self,
        observation: AgentObservation,
        parts: Iterable[MultimodalPart],
        *,
        observation_modality: str = "multimodal",
        extra_state: Mapping[str, JsonValue] | None = None,
    ) -> AgentObservation:
        if not isinstance(observation, AgentObservation):
            raise TypeError("multimodal observation source must be AgentObservation")
        if not observation_modality.strip():
            raise ValueError("multimodal observation modality is required")
        materialized = tuple(parts)
        if any(not isinstance(part, MultimodalPart) for part in materialized):
            raise TypeError("multimodal observation parts must be typed MultimodalPart values")
        if extra_state is not None and not isinstance(extra_state, Mapping):
            raise TypeError("multimodal observation extra_state must be a mapping")

        serialized_parts: list[JsonObject] = []
        refs = list(observation.artifact_refs)
        for part in materialized:
            serialized_parts.append({
                "role": part.role,
                "part_id": part.part_id,
                "modality_id": part.modality_id,
                "encoding": part.encoding,
                "sequence_index": part.sequence_index,
                "timestamp_ns": part.timestamp_ns,
                "duration_ns": part.duration_ns,
                "coordinate_frame": part.coordinate_frame,
                "content_sha256": part.content.sha256,
                "content_media_type": part.content.media_type,
                "content_size_bytes": part.content.size_bytes,
                "metadata": dict(part.metadata),
                "source_refs": list(part.source_refs),
            })
            refs.extend((part.content.sha256, *part.source_refs))

        state: JsonObject = dict(observation.state)
        state["multimodal"] = {
            "parts": serialized_parts,
            "part_count": len(serialized_parts),
        }
        if extra_state:
            state.update(extra_state)
        deduplicated_refs = tuple(dict.fromkeys(refs))
        return AgentObservation(
            observation_id=f"{observation.observation_id}:multimodal:{canonical_digest(state)[:12]}",
            generation=observation.generation,
            state=freeze_json(state),
            modality=observation_modality,
            artifact_refs=deduplicated_refs,
            evidence_payload=observation.evidence_payload,
        )


__all__ = ["AgentMultimodalObservationProjector"]
