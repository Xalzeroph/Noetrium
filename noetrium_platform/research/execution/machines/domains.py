"""Domain authoring surfaces for universal research Machines.

These builders fix a semantic domain while compiling to the single
NoetriumUnit IR. Paper-private operations remain legal through custom(),
so new research semantics never require a kernel enum or a new runner.
"""
from __future__ import annotations

from enum import StrEnum



class RuntimeConcern(StrEnum):
    TURN = "turn"
    EVENT = "event"
    CONTEXT = "context"
    COMMUNICATION = "communication"
    LOGICAL_SCHEDULING = "logical_scheduling"
    SYNCHRONIZATION = "synchronization"
    CAPABILITY_MEDIATION = "capability_mediation"
    VISIBILITY = "visibility"
    RECOVERY = "recovery"
    INTERVENTION = "intervention"


class ParticipantConcern(StrEnum):
    ROLE = "role"
    TURN = "turn"
    STATE = "state"
    PLANNING = "planning"
    ACTION = "action"
    INTERACTION = "interaction"
    TOOL_USE = "tool_use"
    INTERRUPTION = "interruption"
    RECOVERY = "recovery"
    VISIBILITY = "visibility"


class MemoryConcern(StrEnum):
    """Standard semantic axes for programmable Memory Machines.

    These are semantic labels, not fixed algorithms. A paper may replace every
    implementation behind them or use custom concerns for genuinely new work.
    """

    ENCODING = "encoding"
    WRITE = "write"
    UPDATE = "update"
    ASSOCIATION = "association"
    INDEX = "index"
    RETRIEVAL = "retrieval"
    RERANKING = "reranking"
    ACCESS = "access"
    TRUST = "trust"
    CONSOLIDATION = "consolidation"
    DECAY = "decay"
    RETENTION = "retention"
    PROJECTION = "projection"
    SCOPE = "scope"
    MIGRATION = "migration"
    RECONCILIATION = "reconciliation"
    RECOVERY = "recovery"


class EnvironmentConcern(StrEnum):
    OBSERVATION = "observation"
    TRANSITION = "transition"
    QUERY = "query"
    BRANCHING = "branching"
    RESET = "reset"
    RECONCILIATION = "reconciliation"
    RECOVERY = "recovery"
    VISIBILITY = "visibility"


class EvaluationConcern(StrEnum):
    INPUT = "input"
    VALIDATION = "validation"
    SCORING = "scoring"
    COMPARISON = "comparison"
    AGGREGATION = "aggregation"
    JUDGMENT = "judgment"
    CALIBRATION = "calibration"
    FINALIZATION = "finalization"


class AnalysisConcern(StrEnum):
    TRANSFORM = "transform"
    STATISTICS = "statistics"
    COMPARISON = "comparison"
    SELECTION = "selection"
    AGGREGATION = "aggregation"
    FIGURE = "figure"
    TABLE = "table"
    CLAIM = "claim"


class PublicationConcern(StrEnum):
    ASSEMBLY = "assembly"
    VALIDATION = "validation"
    CLAIM_BINDING = "claim_binding"
    FIGURE_BINDING = "figure_binding"
    TABLE_BINDING = "table_binding"
    MANIFEST = "manifest"
    FINALIZATION = "finalization"


class OptimizationConcern(StrEnum):
    PROPOSAL = "proposal"
    MUTATION = "mutation"
    EVALUATION = "evaluation"
    SELECTION = "selection"
    GENERATION = "generation"
    BUDGET = "budget"
    TERMINATION = "termination"
    RECOVERY = "recovery"


class ExperimentConcern(StrEnum):
    DESIGN = "design"
    ASSIGNMENT = "assignment"
    SCHEDULING = "scheduling"
    OBSERVATION = "observation"
    ADAPTATION = "adaptation"
    REPLICATION = "replication"
    AGGREGATION = "aggregation"
    STOPPING = "stopping"
    FINALIZATION = "finalization"


class RunConcern(StrEnum):
    LIFECYCLE = "lifecycle"
    CYCLE = "cycle"
    CHECKPOINT = "checkpoint"
    CONTROL = "control"
    RECOVERY = "recovery"
    EVIDENCE = "evidence"
    FINALIZATION = "finalization"


__all__ = [
    "AnalysisConcern",
    "EnvironmentConcern",
    "EvaluationConcern",
    "ExperimentConcern",
    "MemoryConcern",
    "OptimizationConcern",
    "ParticipantConcern",
    "PublicationConcern",
    "RunConcern",
    "RuntimeConcern",
]
