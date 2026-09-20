"""Side-effect-free compilation seam for downstream research methods."""
from __future__ import annotations

from noetrium_platform.foundation.portfolio.api import ProjectManifest
from noetrium_platform.research.experimentation.binding import ResearchBindingContribution
from noetrium_platform.research.experimentation.study.api import ResearchStudyDefinition

from .research_compiler import (
    CompiledResearchPlan,
    compile_research_plan,
    resolve_research_requirements,
)


def compile_research_method(
    definition: ResearchStudyDefinition,
    project_manifest: ProjectManifest,
    binding: ResearchBindingContribution,
) -> CompiledResearchPlan:
    """Compile one study through the canonical requirement-resolution path."""
    resolution = resolve_research_requirements(definition, project_manifest)
    return compile_research_plan(definition, resolution, binding)


__all__ = ["compile_research_method"]
