from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult
from noetrium_platform.capabilities.participant.core.api import BoundParticipant, BoundParticipants
from noetrium_platform.capabilities.participant.core.api.runtime_ports import ParticipantResolutionPort
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantTopology, ExperimentSpec


class ExperimentComponentBinder:
    """Translate ExperimentSpec topology into generic frozen participant bindings."""

    def __init__(self, resolver: ParticipantResolutionPort) -> None:
        self._resolver = resolver

    def bind(self, spec: ExperimentSpec, context: ExecutionContext) -> BoundParticipants:
        rows: list[OperationResult[JsonValue]] = []
        bound: list[BoundParticipant] = []
        topology = ExperimentParticipantTopology.from_spec(spec)
        for participant in topology.ordered():
            resolved, operation = self._resolver.resolve(participant.runtime_binding(), context)
            bound.append(resolved)
            rows.append(operation)
        return BoundParticipants(tuple(bound), tuple(rows))


__all__ = ["ExperimentComponentBinder"]
