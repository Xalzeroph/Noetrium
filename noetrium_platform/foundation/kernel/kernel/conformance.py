"""Golden-history conformance for Machine implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .canonical import canonical_digest
from .machine import MachineCommand, MachineCommit, MachineConflict
from .runtime import MachineInterpreterPort, MachineRuntime


class MachineConformanceError(AssertionError):
    """Two implementations or one runtime violated the Machine contract."""


@dataclass(frozen=True, slots=True)
class CommitProjection:
    revision: int
    commit_id: str
    state_digest: str
    event_digest: str
    effect_intent_refs: tuple[str, ...]
    emitted_command_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConformanceRun:
    implementation_id: str
    projections: tuple[CommitProjection, ...]
    history_digest: str = ""

    def __post_init__(self) -> None:
        if not self.history_digest:
            object.__setattr__(
                self,
                "history_digest",
                canonical_digest({
                    "implementation_id": self.implementation_id,
                    "projections": self.projections,
                }),
            )


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    runs: tuple[ConformanceRun, ...]
    common_history_digest: str


def _projection(commit: MachineCommit) -> CommitProjection:
    return CommitProjection(
        commit.revision,
        commit.commit_id,
        commit.state_digest,
        canonical_digest(commit.event_payloads),
        commit.effect_intent_refs,
        tuple(command.command_id for command in commit.emitted_commands),
    )


class MachineConformanceHarness:
    """Run identical commands against fresh implementations and compare facts."""

    def compare(
        self,
        *,
        builders: Mapping[str, Callable[[], tuple[MachineRuntime, MachineInterpreterPort]]],
        commands: tuple[MachineCommand, ...],
        initial_state: dict[str, object] | None = None,
    ) -> ConformanceReport:
        if not builders:
            raise ValueError("at least one machine implementation is required")
        if len(set(builders)) != len(builders):
            raise ValueError("implementation ids must be unique")
        runs: list[ConformanceRun] = []
        for implementation_id in sorted(builders):
            runtime, interpreter = builders[implementation_id]()
            snapshot = runtime.open({} if initial_state is None else initial_state)
            projections: list[CommitProjection] = []
            for command in commands:
                if command.machine_id != runtime.machine_id:
                    raise MachineConformanceError(
                        f"{implementation_id}: command targets a different machine"
                    )
                commit = runtime.step(command, interpreter)
                projections.append(_projection(commit))
            runs.append(ConformanceRun(implementation_id, tuple(projections)))
        reference = runs[0].projections
        for run in runs[1:]:
            if run.projections != reference:
                raise MachineConformanceError(
                    f"golden history mismatch: {runs[0].implementation_id} != {run.implementation_id}"
                )
        digest = canonical_digest(reference)
        return ConformanceReport(tuple(runs), digest)

    def verify_runtime_contract(
        self,
        *,
        runtime: MachineRuntime,
        interpreter: MachineInterpreterPort,
        commands: tuple[MachineCommand, ...],
        initial_state: dict[str, object] | None = None,
    ) -> ConformanceRun:
        runtime.open({} if initial_state is None else initial_state)
        commits = [runtime.step(command, interpreter) for command in commands]
        if commits:
            duplicate = runtime.step(commands[-1], interpreter)
            if duplicate != commits[-1]:
                raise MachineConformanceError("duplicate command is not idempotent")
            stale = MachineCommand(
                command_id=f"{commands[-1].command_id}:stale",
                machine_id=runtime.machine_id,
                expected_revision=0,
                kind=commands[-1].kind,
                payload=commands[-1].payload,
                scope=commands[-1].scope,
            )
            try:
                runtime.step(stale, interpreter)
            except MachineConflict:
                pass
            else:
                raise MachineConformanceError("stale command was accepted")
        projections = tuple(_projection(commit) for commit in commits)
        return ConformanceRun("runtime", projections)


__all__ = [
    "CommitProjection",
    "ConformanceReport",
    "ConformanceRun",
    "MachineConformanceError",
    "MachineConformanceHarness",
]
