from __future__ import annotations

from typing import Protocol

from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    ExperimentTaskSpec,
)
from noetrium_platform.research.execution.api import MethodRunResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .contracts import (
    WorkloadGraphResult,
    WorkloadEvaluation,
    WorkloadMethodInvocation,
    WorkloadTaskResult,
)


class WorkloadMethodCompilerPort(Protocol):
    """Compile one experiment task into exactly one MethodProgram invocation."""

    def compile(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
    ) -> WorkloadMethodInvocation: ...


class WorkloadMethodResultAdapterPort(Protocol):
    """Own benchmark/domain result interpretation, not execution control flow."""

    def evaluate(
        self,
        task: ExperimentTaskSpec,
        result: MethodRunResult,
    ) -> WorkloadEvaluation: ...


class WorkloadTaskExecutionPort(Protocol):
    """Single-task operation seam consumed by Experiment/Run Programs."""

    def execute_one(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
    ) -> WorkloadTaskResult: ...


class WorkloadGraphExecutionPort(Protocol):
    """Universal assignment workload graph execution seam."""

    def execute_graph(
        self,
        tasks: tuple[ExperimentTaskSpec, ...],
        workload: AssignmentWorkload,
        context: ExecutionContext,
    ) -> WorkloadGraphResult: ...


__all__ = [
    "WorkloadGraphExecutionPort",
    "WorkloadMethodCompilerPort",
    "WorkloadMethodResultAdapterPort",
    "WorkloadTaskExecutionPort",
]
