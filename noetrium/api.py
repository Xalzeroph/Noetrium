"""The single downstream API for Noetrium.

Lower system APIs are internal composition contracts. Research projects import
only this module, which re-exports the top-level Product Research OS surface.
"""
from __future__ import annotations

from noetrium_platform.product import api as _product
from noetrium_platform.product.api import (
    RESEARCH_PROJECT_BLUEPRINT_SCHEMA,
    ResearchDefinitionRef,
    ResearchProjectBlueprint,
    decode_research_project_blueprint,
    encode_research_project_blueprint,
    research_project_blueprint_document,
    ResearchBranch,
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchDefinition,
    ResearchDefinitionKind,
    ResearchDependency,
    ResearchExecutionTarget,
    ResearchGraphRevision,
    ResearchImpactState,
    ResearchImplementation,
    ResearchMethodProgramImplementation,
    ResearchInputBinding,
    ResearchNode,
    ResearchNodeImpact,
    ResearchNodeKind,
    ResearchPortfolioDependency,
    ResearchPortfolioBuilder,
    ResearchNodeRef,
    ResearchOS,
    ResearchOutputSpec,
    ResearchPortfolio,
    ResearchProgram,
    ResearchProgramBuilder,
    ResearchRevisionDiff,
    ResearchTag,
    ResearchValueKind,
)

__all__ = _product.__all__
