"""Stable root facade for Noetrium product operations.

This module is intentionally a thin re-export. Domain ownership remains in the
product/operator plane, while downstream applications get one discoverable
contract surface.
"""

from noetrium_platform.product.operator.api import (
    ResearchAction,
    ResearchApplicationPort,
    ResearchFacade,
    ResearchOperationFailure,
    ResearchRequest,
    ResearchResult,
    ProjectTestStage,
    ProjectTestStageReceipt,
)

__all__ = [
    "ResearchAction",
    "ResearchApplicationPort",
    "ResearchFacade",
    "ResearchOperationFailure",
    "ResearchRequest",
    "ResearchResult",
    "ProjectTestStage",
    "ProjectTestStageReceipt",
]