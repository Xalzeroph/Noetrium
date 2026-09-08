from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.model.api import MultimodalPart

from ..api.cognition import AgentObservation
from ..api.cognition_ports import AgentObservationPort

from .multimodal import AgentMultimodalObservationProjector


class AgentObservationPartSourcePort(Protocol):
    """Capture arbitrary typed content parts for one observation boundary."""

    def capture(self, context: ExecutionContext) -> Iterable[MultimodalPart]:
        ...


class MultimodalAgentObservationPort(AgentObservationPort):
    """Compose a normal observation source with arbitrary multimodal capture."""

    def __init__(
        self,
        observation: AgentObservationPort,
        parts: AgentObservationPartSourcePort,
        *,
        projector: AgentMultimodalObservationProjector | None = None,
        observation_modality: str = "multimodal",
    ) -> None:
        if not callable(getattr(observation, "observe", None)):
            raise TypeError("observation must implement observe()")
        if not callable(getattr(parts, "capture", None)):
            raise TypeError("parts must implement capture()")
        if type(observation_modality) is not str or not observation_modality.strip():
            raise ValueError("observation_modality must be non-empty")
        self._observation = observation
        self._parts = parts
        self._projector = projector or AgentMultimodalObservationProjector()
        self._observation_modality = observation_modality

    def observe(self, context: ExecutionContext) -> AgentObservation:
        base = self._observation.observe(context)
        captured = self._parts.capture(context)
        return self._projector.project(
            base,
            captured,
            observation_modality=self._observation_modality,
        )


__all__ = ["AgentObservationPartSourcePort", "MultimodalAgentObservationPort"]

