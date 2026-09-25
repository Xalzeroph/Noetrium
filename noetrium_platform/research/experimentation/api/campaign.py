"""Cross-study research campaign contracts and pure compilation.

A campaign groups already-authoritative research studies. It never owns benchmark,
method, model, metric, evidence, or run truth; its digest only binds the exact
compiled research plans selected for one orchestration batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.binding import (
    ResearchBindingContribution,
    ResearchRequirementResolution,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    StudyExecutionPlan,
    ResearchStudyDefinition,
)
from .research_compiler import CompiledResearchPlan, compile_research_plan

_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


def _token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical token")
    return value


@dataclass(frozen=True, slots=True)
class ResearchCampaignStudy:
    lane_id: str
    research_plan_digest: str
    plan: StudyExecutionPlan
    depends_on_lane_ids: tuple[str, ...] = ()
    study_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign lane_id")
        require_sha256(self.research_plan_digest, "campaign research_plan_digest")
        if type(self.plan) is not StudyExecutionPlan:
            raise TypeError("campaign study plan must be StudyExecutionPlan")
        self.plan.assert_consistent()
        if type(self.depends_on_lane_ids) is not tuple:
            raise TypeError("campaign dependencies must be a tuple")
        dependencies = tuple(
            _token(value, "campaign dependency lane_id")
            for value in self.depends_on_lane_ids
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("campaign dependencies must not contain duplicates")
        if self.lane_id in dependencies:
            raise ValueError("campaign lane cannot depend on itself")
        dependencies = tuple(sorted(dependencies))
        object.__setattr__(self, "depends_on_lane_ids", dependencies)
        object.__setattr__(
            self,
            "study_digest",
            canonical_digest(
                {
                    "lane_id": self.lane_id,
                    "research_plan_digest": self.research_plan_digest,
                    "study_id": self.plan.protocol.study_id,
                    "study_plan_digest": self.plan.plan_digest,
                    "depends_on_lane_ids": dependencies,
                }
            ),
        )

    @classmethod
    def from_compiled(
        cls,
        lane_id: str,
        compiled: CompiledResearchPlan,
        *,
        depends_on_lane_ids: tuple[str, ...] = (),
    ) -> "ResearchCampaignStudy":
        if type(compiled) is not CompiledResearchPlan:
            raise TypeError("campaign study compilation requires CompiledResearchPlan")
        return cls(
            lane_id,
            compiled.research_plan_digest,
            compiled.experiment_plan,
            depends_on_lane_ids,
        )


def _validate_dependency_graph(
    dependencies_by_lane: dict[str, tuple[str, ...]],
) -> None:
    known_lane_ids = set(dependencies_by_lane)
    for lane_id, dependencies in dependencies_by_lane.items():
        unknown = tuple(
            dependency
            for dependency in dependencies
            if dependency not in known_lane_ids
        )
        if unknown:
            raise ValueError(
                f"campaign lane {lane_id!r} depends on unknown lanes: {unknown}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(lane_id: str) -> None:
        if lane_id in visited:
            return
        if lane_id in visiting:
            raise ValueError(f"campaign dependency cycle at lane {lane_id!r}")
        visiting.add(lane_id)
        for dependency in dependencies_by_lane[lane_id]:
            visit(dependency)
        visiting.remove(lane_id)
        visited.add(lane_id)

    for lane_id in sorted(dependencies_by_lane):
        visit(lane_id)


@dataclass(frozen=True, slots=True)
class ResearchCampaignPlan:
    campaign_id: str
    studies: tuple[ResearchCampaignStudy, ...]
    campaign_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.campaign_id, "campaign_id")
        if type(self.studies) is not tuple or not self.studies:
            raise TypeError("research campaign studies must be a non-empty tuple")
        if any(type(row) is not ResearchCampaignStudy for row in self.studies):
            raise TypeError("research campaign studies must contain ResearchCampaignStudy")
        studies = tuple(sorted(self.studies, key=lambda row: row.lane_id))
        lane_ids = tuple(row.lane_id for row in studies)
        if len(lane_ids) != len(set(lane_ids)):
            raise ValueError("research campaign lane identities must be unique")
        research_digests = tuple(row.research_plan_digest for row in studies)
        if len(research_digests) != len(set(research_digests)):
            raise ValueError(
                "duplicate compiled research plans belong inside Study repetitions, not campaign lanes"
            )
        _validate_dependency_graph(
            {
                study.lane_id: study.depends_on_lane_ids
                for study in studies
            }
        )

        object.__setattr__(self, "studies", studies)
        object.__setattr__(
            self,
            "campaign_digest",
            canonical_digest(
                {
                    "campaign_id": self.campaign_id,
                    "studies": tuple(row.study_digest for row in studies),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchCampaignCompilationUnit:
    lane_id: str
    definition: ResearchStudyDefinition
    resolution: ResearchRequirementResolution
    binding: ResearchBindingContribution
    depends_on_lane_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign compilation lane_id")
        if type(self.definition) is not ResearchStudyDefinition:
            raise TypeError("campaign compilation definition must be ResearchStudyDefinition")
        if type(self.resolution) is not ResearchRequirementResolution:
            raise TypeError("campaign compilation resolution must be ResearchRequirementResolution")
        if type(self.binding) is not ResearchBindingContribution:
            raise TypeError("campaign compilation binding must be ResearchBindingContribution")
        if type(self.depends_on_lane_ids) is not tuple:
            raise TypeError("campaign compilation dependencies must be a tuple")
        dependencies = tuple(
            _token(value, "campaign compilation dependency lane_id")
            for value in self.depends_on_lane_ids
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("campaign compilation dependencies must not contain duplicates")
        if self.lane_id in dependencies:
            raise ValueError("campaign compilation lane cannot depend on itself")
        object.__setattr__(self, "depends_on_lane_ids", tuple(sorted(dependencies)))


@dataclass(frozen=True, slots=True)
class CompiledResearchCampaignLane:
    lane_id: str
    research_plan: CompiledResearchPlan

    def __post_init__(self) -> None:
        _token(self.lane_id, "compiled campaign lane_id")
        if type(self.research_plan) is not CompiledResearchPlan:
            raise TypeError("compiled campaign lane requires CompiledResearchPlan")


@dataclass(frozen=True, slots=True)
class CompiledResearchCampaign:
    plan: ResearchCampaignPlan
    lanes: tuple[CompiledResearchCampaignLane, ...]

    def __post_init__(self) -> None:
        if type(self.plan) is not ResearchCampaignPlan:
            raise TypeError("compiled research campaign requires ResearchCampaignPlan")
        if type(self.lanes) is not tuple or not self.lanes:
            raise TypeError("compiled research campaign lanes must be a non-empty tuple")
        if any(type(row) is not CompiledResearchCampaignLane for row in self.lanes):
            raise TypeError("compiled research campaign lanes must be typed")
        lanes = tuple(sorted(self.lanes, key=lambda row: row.lane_id))
        object.__setattr__(self, "lanes", lanes)
        if tuple(row.lane_id for row in lanes) != tuple(
            row.lane_id for row in self.plan.studies
        ):
            raise ValueError("compiled campaign lanes drifted from execution campaign lanes")
        for lane, study in zip(lanes, self.plan.studies, strict=True):
            if lane.research_plan.research_plan_digest != study.research_plan_digest:
                raise ValueError("compiled campaign research identity drifted")
            if lane.research_plan.experiment_plan.plan_digest != study.plan.plan_digest:
                raise ValueError("compiled campaign study plan drifted")


def compile_research_campaign(
    campaign_id: str,
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    _token(campaign_id, "campaign_id")
    if type(units) is not tuple or not units:
        raise TypeError("campaign compilation units must be a non-empty tuple")
    if any(type(row) is not ResearchCampaignCompilationUnit for row in units):
        raise TypeError("campaign compilation units must be typed")
    lane_ids = tuple(row.lane_id for row in units)
    if len(lane_ids) != len(set(lane_ids)):
        raise ValueError("campaign compilation lane identities must be unique")
    dependencies_by_lane = {
        row.lane_id: row.depends_on_lane_ids
        for row in units
    }
    _validate_dependency_graph(dependencies_by_lane)
    compiled_lanes = tuple(
        sorted(
            (
                CompiledResearchCampaignLane(
                    row.lane_id,
                    compile_research_plan(row.definition, row.resolution, row.binding),
                )
                for row in units
            ),
            key=lambda row: row.lane_id,
        )
    )
    plan = ResearchCampaignPlan(
        campaign_id,
        tuple(
            ResearchCampaignStudy.from_compiled(
                row.lane_id,
                row.research_plan,
                depends_on_lane_ids=dependencies_by_lane[row.lane_id],
            )
            for row in compiled_lanes
        ),
    )
    return CompiledResearchCampaign(plan, compiled_lanes)



__all__ = [
    "CompiledResearchCampaign",
    "CompiledResearchCampaignLane",
    "ResearchCampaignCompilationUnit",
    "ResearchCampaignPlan",
    "ResearchCampaignStudy",
    "compile_research_campaign",
]
