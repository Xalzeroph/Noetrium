"""Typed research-result and semantic query contracts."""

from .contracts import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchQueryGap,
    ResearchQueryGapKind,
    ResearchQuerySourceError,
    ResearchResultKind,
    ResearchResultPage,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchResultReference,
    ResearchSourceCut,
    ResearchSourceDisposition,
    ResearchSourceSnapshot,
    ResearchSourceStatus,
)
from .ports import ResearchResultQueryPort, ResearchResultSourcePort
from .semantic import (
    SemanticSimilarityMatch,
    SemanticSimilarityMetric,
    SemanticSimilarityQuery,
    SemanticSimilarityQueryPort,
    SemanticSimilarityResult,
)

__all__ = [
    "ResearchDimension", "ResearchDimensionKind", "ResearchQueryGap",
    "ResearchQueryGapKind", "ResearchQuerySourceError", "ResearchResultKind",
    "ResearchResultPage", "ResearchResultQuery", "ResearchResultQueryPort",
    "ResearchResultRecord", "ResearchResultReference", "ResearchResultSourcePort",
    "ResearchSourceCut", "ResearchSourceDisposition", "ResearchSourceSnapshot",
    "ResearchSourceStatus", "SemanticSimilarityMatch", "SemanticSimilarityMetric",
    "SemanticSimilarityQuery", "SemanticSimilarityQueryPort", "SemanticSimilarityResult",
]
