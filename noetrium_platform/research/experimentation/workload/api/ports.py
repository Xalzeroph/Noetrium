from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

from typing import Protocol

from noetrium_platform.research.experimentation.lifecycle.study.api import (
    validate_assignment_workload,
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
    """Compile one experiment task into exactly one NoetriumUnit invocation."""

    def compile(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadMethodInvocation: ...


class WorkloadMethodResultAdapterPort(Protocol):
    """Own benchmark/domain result interpretation, not execution control flow."""

    def evaluate(
        self,
        task: NoetriumUnit,
        result: MethodRunResult,
    ) -> WorkloadEvaluation: ...


class WorkloadTaskExecutionPort(Protocol):
    """Single-task operation seam consumed by Experiment/Run Programs."""

    def execute_one(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadTaskResult: ...


class WorkloadExecutionPort(Protocol):
    """Universal workload machine seam: one task or an immutable assignment graph."""

    @property
    def identity_digest(self) -> str: ...

    def execute_one(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadTaskResult: ...

    def execute_graph(
        self,
        tasks: tuple[NoetriumUnit, ...],
        workload: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadGraphResult: ...


__all__ = [
    "WorkloadExecutionPort",
    "WorkloadMethodCompilerPort",
    "WorkloadMethodResultAdapterPort",
    "WorkloadTaskExecutionPort",
]
