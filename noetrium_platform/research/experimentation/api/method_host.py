"""Side-effect-free compilation seam for downstream research methods."""
from __future__ import annotations
from noetrium_platform.research.experimentation.binding import ResearchBindingContribution
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import require_study_unit

from .research_compiler import (
    compile_research_plan,
    resolve_research_requirements,
)


def compile_research_method(
    definition: NoetriumUnit,
    project_manifest: NoetriumUnit,
    binding: ResearchBindingContribution,
) -> NoetriumUnit:
    require_study_unit(definition)
    """Compile one study through the canonical requirement-resolution path."""
    resolution = resolve_research_requirements(definition, project_manifest)
    return compile_research_plan(definition, resolution, binding)


__all__ = ["compile_research_method"]
