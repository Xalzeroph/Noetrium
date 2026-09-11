"""Research Run contract backed by the authoritative MachineRuntime.

This facade owns the research-facing run seam without copying Machine state.
All accepted execution facts remain in the Machine journal; records only
reference the head and immutable result identities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from noetrium_platform.foundation.kernel.kernel import (
    MachineCommand,
    MachineCommit,
    MachineRuntime,
    MachineSnapshot,
    MachineInterpreterPort,
    RunBinding,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.experimentation.record import (
    ComparisonRecord,
    ForkRecord,
    ResearchPackage,
    ResearchRunRecord,
    fork_run,
)


def _status(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("research run status must be non-empty")
    return value


@dataclass(frozen=True, slots=True)
class ResearchRunSession:
    """Run-level facade over one MachineRuntime authority."""

    runtime: MachineRuntime
    binding_digest: str
    binding: RunBinding | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, MachineRuntime):
            raise TypeError("research run session requires MachineRuntime")
        require_sha256(self.binding_digest, "research run binding_digest")
        if self.binding is not None:
            if not isinstance(self.binding, RunBinding):
                raise TypeError("research run binding must be RunBinding")
            if self.binding.program_digest != self.runtime.program.program_digest:
                raise ValueError("research run binding program_digest does not match runtime")
            expected_machine = canonical_digest(self.runtime.identity)
            if self.binding.machine_implementation_digest != expected_machine:
                raise ValueError("research run binding machine digest does not match runtime")
            object.__setattr__(self, "binding_digest", self.binding.binding_digest)

    @property
    def run_id(self) -> str:
        return self.runtime.machine_id

    def open(self, initial_state: dict[str, Any] | None = None) -> MachineSnapshot:
        return self.runtime.open(initial_state)

    def step(
        self,
        command: MachineCommand,
        interpreter: MachineInterpreterPort,
    ) -> MachineCommit:
        return self.runtime.step(command, interpreter)

    def record(
        self,
        *,
        status: str,
        result: Any | None = None,
    ) -> ResearchRunRecord:
        _status(status)
        head = self.runtime.journal.latest(self.run_id)
        if head is None:
            raise RuntimeError("research run record requires an accepted commit")
        result_digest = (
            result if type(result) is str and len(result) == 64
            else canonical_digest({
                "run_id": self.run_id,
                "head_commit_id": head.commit_id,
                "state_digest": head.state_digest,
                "result": result,
                "status": status,
            })
        )
        require_sha256(result_digest, "research run result_digest")
        return ResearchRunRecord(
            run_id=self.run_id,
            head_commit_id=head.commit_id,
            program_digest=self.runtime.program.program_digest,
            binding_digest=self.binding_digest,
            result_digest=result_digest,
            status=status,
        )


    def fork(
        self,
        *,
        target: "ResearchRunSession",
        change: Any,
        isolation_policy: str = "copy_on_write",
    ) -> ForkRecord:
        head = self.runtime.journal.latest(self.run_id)
        if head is None:
            raise RuntimeError("cannot fork a run without an accepted commit")
        if not isinstance(target, ResearchRunSession):
            raise TypeError("fork target must be ResearchRunSession")
        if target.run_id == self.run_id:
            raise ValueError("fork target must have a new run identity")
        change_digest = (
            change if type(change) is str and len(change) == 64
            else canonical_digest(change)
        )
        require_sha256(change_digest, "fork change_digest")
        target.open(dict(head.state))
        return fork_run(
            source_run_id=self.run_id,
            source_commit_id=head.commit_id,
            new_run_id=target.run_id,
            change_digest=change_digest,
            isolation_policy=isolation_policy,
        )

    @staticmethod
    def compare(
        *,
        comparison_id: str,
        runs: tuple[ResearchRunRecord, ...],
        evaluator: Any,
        result: Any,
        status: str,
    ) -> ComparisonRecord:
        if type(runs) is not tuple or len(runs) < 2:
            raise ValueError("comparison requires at least two run records")
        run_ids = tuple(item.run_id for item in runs)
        return ComparisonRecord(
            comparison_id=comparison_id,
            run_ids=run_ids,
            evaluator_digest=(
                evaluator if type(evaluator) is str and len(evaluator) == 64
                else canonical_digest(evaluator)
            ),
            result_digest=(
                result if type(result) is str and len(result) == 64
                else canonical_digest(result)
            ),
            status=_status(status),
        )

    @staticmethod
    def package(
        *,
        package_id: str,
        definition: Any,
        runs: tuple[ResearchRunRecord, ...],
        comparisons: tuple[ComparisonRecord, ...] = (),
        forks: tuple[ForkRecord, ...] = (),
        dependencies: tuple[str, ...] = (),
    ) -> ResearchPackage:
        definition_digest = (
            definition if type(definition) is str and len(definition) == 64
            else canonical_digest(definition)
        )
        return ResearchPackage(
            package_id=package_id,
            definition_digest=definition_digest,
            runs=runs,
            comparisons=comparisons,
            forks=forks,
            dependency_digests=dependencies,
        )


__all__ = ["ResearchRunSession"]