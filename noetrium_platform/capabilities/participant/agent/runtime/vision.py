from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest

from ..api.cognition import AgentObservation, JsonObject


@dataclass(frozen=True, slots=True)
class VisionFrame:
    frame_id: str
    generation: str
    artifact_ref: str
    width: int
    height: int
    camera: str = "first_person"

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.frame_id, self.generation, self.artifact_ref, self.camera)):
            raise ValueError("vision frame identity is incomplete")
        if self.width < 1 or self.height < 1:
            raise ValueError("vision frame dimensions must be positive")


@dataclass(frozen=True, slots=True)
class VisionInterpretation:
    frame_id: str
    labels: tuple[str, ...]
    description: str
    confidence: float
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.frame_id.strip()
            or not self.description.strip()
            or isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("vision interpretation is invalid")


class AgentVisionProviderPort(Protocol):
    def interpret(self, frame: VisionFrame, context: ExecutionContext) -> VisionInterpretation: ...


class VisionObservationProjector:
    """Adds optional vision evidence without making visual input mandatory."""

    def project(self, observation: AgentObservation, frame: VisionFrame, interpretation: VisionInterpretation) -> AgentObservation:
        if frame.generation != observation.generation:
            raise ValueError("vision frame generation does not match observation")
        state: JsonObject = dict(observation.state)
        state["vision"] = {
            "frame_id": interpretation.frame_id,
            "labels": list(interpretation.labels),
            "description": interpretation.description,
            "confidence": interpretation.confidence,
        }
        refs = tuple(dict.fromkeys((*observation.artifact_refs, frame.artifact_ref, *interpretation.evidence_refs)))
        return AgentObservation(
            observation_id=f"{observation.observation_id}:vision:{canonical_digest(state)[:12]}",
            generation=observation.generation,
            state=state,
            modality="world+vision",
            artifact_refs=refs,
            evidence_payload=observation.evidence_payload,
        )


__all__ = ["AgentVisionProviderPort", "VisionFrame", "VisionInterpretation", "VisionObservationProjector"]
