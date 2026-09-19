from __future__ import annotations

from typing import Protocol, TypeVar

from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.execution.decision.cycle_result import DecisionCycleResult
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.lifecycle.api import RunSessionPort
from noetrium_platform.foundation.kernel.kernel import JsonInput


TaskT = TypeVar("TaskT")


class RunRuntimePort(Protocol):
    """Parent-facing programmable Runtime port for opening a long-lived run."""

    def open(
        self,
        spec: ExperimentSpec,
        identity: RunIdentity,
        *,
        restore_checkpoint_id: str | None = None,
        restore_cycle_identity: DecisionCycleIdentity | None = None,
    ) -> RunSessionPort: ...


class DecisionCycleRuntimePort(Protocol):
    """Parent-facing programmable one-cycle Runtime port."""

    def run(
        self,
        spec: ExperimentSpec,
        identity: DecisionCycleIdentity,
        *,
        task: TaskT,
        input_kind: str,
        input_payload: JsonInput,
    ) -> DecisionCycleResult: ...


__all__ = ["DecisionCycleRuntimePort", "RunRuntimePort", "RunSessionPort"]
