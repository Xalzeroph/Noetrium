"""Public, side-effect-free host for downstream research methods.

The host owns orchestration of the public compiler seam only. Provider, runtime,
resource, checkpoint, and evidence authorities remain injected producer ports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.research.experimentation.binding import ResearchBindingContribution
from noetrium_platform.research.experimentation.api.research_compiler import (
    CompiledResearchPlan,
    compile_research_plan,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.study.api import ResearchStudyDefinition
from noetrium_platform.foundation.portfolio.api import ProjectManifest


@runtime_checkable
class ResearchMethodHostPort(Protocol):
    def compile_method(
        self,
        definition: ResearchStudyDefinition,
        project_manifest: ProjectManifest,
        binding: ResearchBindingContribution,
    ) -> CompiledResearchPlan: ...


class ResearchMethodHost:
    """Canonical Level-0 host; compilation performs no external side effects."""

    def compile_method(
        self,
        definition: ResearchStudyDefinition,
        project_manifest: ProjectManifest,
        binding: ResearchBindingContribution,
    ) -> CompiledResearchPlan:
        resolution = resolve_research_requirements(definition, project_manifest)
        return compile_research_plan(definition, resolution, binding)


__all__ = ["ResearchMethodHost", "ResearchMethodHostPort"]
