from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from .contracts import ExperimentParticipantSpec, ExperimentSpec


def _append_reverse_edges(
    row: ExperimentParticipantSpec,
    dependents: dict[str, list[str]],
) -> None:
    for dependency in row.depends_on_roles:
        if dependency in dependents:
            dependents[dependency].append(row.role)


def _dependency_graph(
    participants: tuple[ExperimentParticipantSpec, ...],
) -> tuple[
    dict[str, ExperimentParticipantSpec],
    dict[str, int],
    dict[str, list[str]],
    dict[str, int],
]:
    by_role: dict[str, ExperimentParticipantSpec] = {}
    indegree: dict[str, int] = {}
    dependents: dict[str, list[str]] = {}
    positions: dict[str, int] = {}
    for index, row in enumerate(participants):
        by_role[row.role] = row
        indegree[row.role] = len(row.depends_on_roles)
        dependents[row.role] = []
        positions[row.role] = index
    for row in participants:
        _append_reverse_edges(row, dependents)
    return by_role, indegree, dependents, positions

def _release_dependents(role: str, dependents: dict[str, list[str]], indegree: dict[str, int]) -> list[str]:
    released: list[str] = []
    for dependent in dependents[role]:
        indegree[dependent] -= 1
        if indegree[dependent] == 0:
            released.append(dependent)
    return released


def _advance_wave(
    ready: list[str],
    *,
    by_role: dict[str, ExperimentParticipantSpec],
    dependents: dict[str, list[str]],
    indegree: dict[str, int],
    positions: dict[str, int],
) -> tuple[list[ExperimentParticipantSpec], list[str]]:
    emitted: list[ExperimentParticipantSpec] = []
    next_ready: list[str] = []
    for role in ready:
        emitted.append(by_role[role])
        next_ready.extend(_release_dependents(role, dependents, indegree))
    next_ready.sort(key=positions.__getitem__)
    return emitted, next_ready


@dataclass(frozen=True, slots=True)
class ExperimentParticipantTopology:
    participants: tuple[ExperimentParticipantSpec, ...]

    @classmethod
    def from_spec(cls, spec: ExperimentSpec) -> "ExperimentParticipantTopology":
        topology = cls(spec.participants)
        topology.validate()
        return topology

    def validate(self) -> None:
        roles = [row.role for row in self.participants]
        if len(roles) != len(set(roles)):
            raise ValueError("Experiment participant roles must be unique")
        known = set(roles)
        for row in self.participants:
            missing = set(row.depends_on_roles) - known
            if missing:
                raise ValueError(f"participant {row.role} has missing dependencies: {sorted(missing)}")
        self.ordered()

    def waves(self) -> tuple[tuple[ExperimentParticipantSpec, ...], ...]:
        by_role, indegree, dependents, positions = _dependency_graph(self.participants)
        ready = [row.role for row in self.participants if indegree[row.role] == 0]
        waves: list[tuple[ExperimentParticipantSpec, ...]] = []
        emitted_count = 0
        while ready:
            emitted, ready = _advance_wave(
                ready, by_role=by_role, dependents=dependents,
                indegree=indegree, positions=positions,
            )
            waves.append(tuple(emitted))
            emitted_count += len(emitted)
        if emitted_count != len(self.participants):
            pending = sorted(role for role, degree in indegree.items() if degree > 0)
            raise ValueError(f"participant dependency cycle: {pending}")
        return tuple(waves)

    def ordered(self) -> tuple[ExperimentParticipantSpec, ...]:
        return tuple(item for wave in self.waves() for item in wave)

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = ["ExperimentParticipantTopology"]
