"""Research workbench API boundary.

Providers and runtime pipelines are composition-owned and are not re-exported
from the public package root.
"""

from .api import (
    AggregationFunction, BaselineRegistryPort, DataColumn,
    DataTable, EvaluationContext, EvaluationStage, FigureCategory, FigureKind, FigureOutputFormat,
    GroupComparison, InferenceResult, MetricSummary,
    MissingValuePolicy, MultipleComparisonMethod, MultipleComparisonResult, PairedComparison,
    RenderedResearchPackage, ResearchEvaluation, ResearchReport, SplitStrategy,
    MeasurementRecordTableAdapter, StudyObservationTableAdapter,
)

__all__ = [
    "AggregationFunction", "BaselineRegistryPort",
    "DataColumn", "DataTable", "EvaluationContext", "EvaluationStage",
    "FigureCategory", "FigureKind", "FigureOutputFormat",
    "GroupComparison", "InferenceResult",
    "MetricSummary", "MeasurementRecordTableAdapter", "MissingValuePolicy",
    "MultipleComparisonMethod", "MultipleComparisonResult", "PairedComparison",
    "RenderedResearchPackage", "ResearchEvaluation", "ResearchReport", "SplitStrategy",
    "StudyObservationTableAdapter",
]
