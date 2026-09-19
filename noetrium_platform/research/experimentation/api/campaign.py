"""Cross-study research campaign contracts and pure compilation.

A campaign groups already-authoritative research studies. It never owns benchmark,
method, model, metric, evidence, or run truth; its digest only binds the exact
compiled research plans selected for one orchestration batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.binding import (
    ResearchBindingContribution,
    ResearchRequirementResolution,
)
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyExecutionPort,
    ExperimentPlan,
    ResearchStudyDefinition,
    StudyMatrixExecutionReport,
    StudyMetricAggregationPort,
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
    plan: ExperimentPlan
    study_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign lane_id")
        require_sha256(self.research_plan_digest, "campaign research_plan_digest")
        if type(self.plan) is not ExperimentPlan:
            raise TypeError("campaign study plan must be ExperimentPlan")
        self.plan.assert_consistent()
        object.__setattr__(
            self,
            "study_digest",
            canonical_digest(
                {
                    "lane_id": self.lane_id,
                    "research_plan_digest": self.research_plan_digest,
                    "study_id": self.plan.protocol.study_id,
                    "study_plan_digest": self.plan.plan_digest,
                }
            ),
        )

    @classmethod
    def from_compiled(
        cls,
        lane_id: str,
        compiled: CompiledResearchPlan,
    ) -> "ResearchCampaignStudy":
        if type(compiled) is not CompiledResearchPlan:
            raise TypeError("campaign study compilation requires CompiledResearchPlan")
        return cls(lane_id, compiled.research_plan_digest, compiled.experiment_plan)


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

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign compilation lane_id")
        if type(self.definition) is not ResearchStudyDefinition:
            raise TypeError("campaign compilation definition must be ResearchStudyDefinition")
        if type(self.resolution) is not ResearchRequirementResolution:
            raise TypeError("campaign compilation resolution must be ResearchRequirementResolution")
        if type(self.binding) is not ResearchBindingContribution:
            raise TypeError("campaign compilation binding must be ResearchBindingContribution")


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
            ResearchCampaignStudy.from_compiled(row.lane_id, row.research_plan)
            for row in compiled_lanes
        ),
    )
    return CompiledResearchCampaign(plan, compiled_lanes)


@dataclass(frozen=True, slots=True)
class ResearchCampaignStudyBinding:
    lane_id: str
    adapter: BoundStudyExecutionPort
    aggregation: StudyMetricAggregationPort | None = None

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign binding lane_id")
        if not isinstance(self.adapter, BoundStudyExecutionPort):
            raise TypeError("campaign study adapter must satisfy BoundStudyExecutionPort")
        if self.aggregation is not None and not callable(
            getattr(self.aggregation, "aggregate", None)
        ):
            raise TypeError("campaign study aggregation must satisfy StudyMetricAggregationPort")


class ResearchCampaignLaneState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ResearchCampaignLaneResult:
    lane_id: str
    research_plan_digest: str
    study_plan_digest: str
    state: ResearchCampaignLaneState
    report: StudyMatrixExecutionReport | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        _token(self.lane_id, "campaign result lane_id")
        require_sha256(self.research_plan_digest, "campaign result research_plan_digest")
        require_sha256(self.study_plan_digest, "campaign result study_plan_digest")
        if not isinstance(self.state, ResearchCampaignLaneState):
            raise TypeError("campaign lane state must be ResearchCampaignLaneState")
        if self.state is ResearchCampaignLaneState.SUCCEEDED:
            if type(self.report) is not StudyMatrixExecutionReport:
                raise TypeError("successful campaign lane requires StudyMatrixExecutionReport")
            if self.report.plan_digest != self.study_plan_digest:
                raise ValueError("campaign lane report does not match frozen study plan")
            if self.failure_type is not None or self.failure_message is not None:
                raise ValueError("successful campaign lane cannot carry failure metadata")
        else:
            if self.report is not None:
                raise ValueError("failed campaign lane cannot carry a study report")
            if not isinstance(self.failure_type, str) or not self.failure_type.strip():
                raise ValueError("failed campaign lane requires failure_type")
            if not isinstance(self.failure_message, str) or not self.failure_message.strip():
                raise ValueError("failed campaign lane requires failure_message")


@dataclass(frozen=True, slots=True)
class ResearchCampaignExecutionReport:
    campaign_id: str
    campaign_digest: str
    lanes: tuple[ResearchCampaignLaneResult, ...]

    def __post_init__(self) -> None:
        _token(self.campaign_id, "campaign report campaign_id")
        require_sha256(self.campaign_digest, "campaign report campaign_digest")
        if type(self.lanes) is not tuple or not self.lanes:
            raise TypeError("campaign report lanes must be a non-empty tuple")
        if any(type(row) is not ResearchCampaignLaneResult for row in self.lanes):
            raise TypeError("campaign report lanes must contain ResearchCampaignLaneResult")
        lane_ids = tuple(row.lane_id for row in self.lanes)
        if lane_ids != tuple(sorted(lane_ids)):
            raise ValueError("campaign report lanes must be canonical lane-id order")
        if len(lane_ids) != len(set(lane_ids)):
            raise ValueError("campaign report lane identities must be unique")

    @property
    def succeeded_lane_ids(self) -> tuple[str, ...]:
        return tuple(
            row.lane_id for row in self.lanes
            if row.state is ResearchCampaignLaneState.SUCCEEDED
        )

    @property
    def failed_lane_ids(self) -> tuple[str, ...]:
        return tuple(
            row.lane_id for row in self.lanes
            if row.state is ResearchCampaignLaneState.FAILED
        )


class ResearchCampaignExecutionPort(Protocol):
    def execute(self) -> ResearchCampaignExecutionReport: ...


__all__ = [
    "CompiledResearchCampaign",
    "CompiledResearchCampaignLane",
    "ResearchCampaignCompilationUnit",
    "ResearchCampaignExecutionPort",
    "ResearchCampaignExecutionReport",
    "ResearchCampaignLaneResult",
    "ResearchCampaignLaneState",
    "ResearchCampaignPlan",
    "ResearchCampaignStudy",
    "ResearchCampaignStudyBinding",
    "compile_research_campaign",
]
