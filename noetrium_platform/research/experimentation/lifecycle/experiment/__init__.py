"""Experiment subsystem public contract surface."""

from .api import (
    ExperimentParticipantSpec,
    ExperimentSpec,
    ExperimentTaskSpec,
    ExperimentWorkloadFailure,
    ExperimentTrialProtocolIdentity,
    ExperimentTrialProtocolIdentityMismatch,
    FailureScope,
    FailureScopeRank,
    validate_task_graph,
)

__all__ = [
    "ExperimentParticipantSpec",
    "ExperimentSpec",
    "ExperimentTaskSpec",
    "ExperimentWorkloadFailure",
    "ExperimentTrialProtocolIdentity",
    "ExperimentTrialProtocolIdentityMismatch",
    "FailureScope",
    "FailureScopeRank",
    "validate_task_graph",
]
