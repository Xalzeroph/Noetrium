from __future__ import annotations

"""Public execution-authoring ABI for downstream Research OS projects.

Scientific declarations stay in :mod:`research_authoring`.  This module exposes
only typed execution contracts and generic composition helpers that downstream
projects may implement or instantiate without importing internal Noetrium
composition registries.
"""

from noetrium_platform.capabilities.model.api import (
    ModelProviderProfile,
    ProjectModelBinding,
    ProjectModelBindingSet,
)
from noetrium_platform.research.execution.workflow.api import (
    AsyncMethodAgentLoopPort,
    MethodAgentLoopPort,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    MeasurementRecord,
    MeasurementValue,
    TrialExecutionReceipt,
    TrialExecutionRequest,
    TrialExecutionStageReceipt,
    TrialMeasurementProjectionPort,
    TrialProviderPort,
    TrialTaskProjectionPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    CutWorkloadTrialProvider,
    StandardWorkloadMeasurementProjection,
    WorkloadTrialProvider,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadCompletionReceipt,
    WorkloadCutExecutionPort,
    WorkloadCutResult,
    WorkloadEvaluation,
    WorkloadMethodCompilerPort,
    WorkloadMethodInvocation,
    WorkloadMethodReceipt,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
    WorkloadTaskResult,
)
from noetrium_platform.research.experimentation.workload.runtime import (
    SequentialWorkloadCutBinding,
)


__all__ = [
    "AsyncMethodAgentLoopPort",
    "CutWorkloadTrialProvider",
    "ExperimentTaskSpec",
    "MeasurementRecord",
    "MeasurementValue",
    "MethodAgentLoopPort",
    "ModelProviderProfile",
    "ProjectModelBinding",
    "ProjectModelBindingSet",
    "SequentialWorkloadCutBinding",
    "StandardWorkloadMeasurementProjection",
    "TrialExecutionReceipt",
    "TrialExecutionRequest",
    "TrialExecutionStageReceipt",
    "TrialMeasurementProjectionPort",
    "TrialProviderPort",
    "TrialTaskProjectionPort",
    "WorkloadCompletionReceipt",
    "WorkloadCutExecutionPort",
    "WorkloadCutResult",
    "WorkloadEvaluation",
    "WorkloadMethodCompilerPort",
    "WorkloadMethodInvocation",
    "WorkloadMethodReceipt",
    "WorkloadMethodResultAdapterPort",
    "WorkloadTaskExecutionPort",
    "WorkloadTaskResult",
    "WorkloadTrialProvider",
]
