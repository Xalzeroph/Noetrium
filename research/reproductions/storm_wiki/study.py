from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.freshwiki import FRESHWIKI_BENCHMARK_ID

from .fidelity import STORM_WIKI_REFERENCE_FIDELITY
from .program import build_storm_wiki_method_program


def storm_freshwiki_trial_protocol(
    *,
    search_capability_id: str,
) -> ExperimentTrialProtocolIdentity:
    program = build_storm_wiki_method_program(
        search_capability_id=search_capability_id,
    )
    fidelity = STORM_WIKI_REFERENCE_FIDELITY
    return ExperimentTrialProtocolIdentity(
        "storm.naacl2024.freshwiki.v1",
        canonical_digest({
            "program_digest": program.program_digest,
            "source_commit": fidelity.audited_commit,
            "stage_order": fidelity.stage_order,
            "max_perspectives": fidelity.max_perspectives,
            "max_conversation_turns": fidelity.max_conversation_turns,
            "search_top_k": fidelity.search_top_k,
            "search_capability_id": search_capability_id,
        }),
    )


def build_storm_freshwiki_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
    search_capability_id: str,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != FRESHWIKI_BENCHMARK_ID:
        raise ValueError("STORM study requires FreshWiki")
    if not benchmark.selected_tasks(split_id):
        raise ValueError("STORM FreshWiki study requires a non-empty split")
    fidelity = STORM_WIKI_REFERENCE_FIDELITY
    return Study(
        project_id="storm-naacl2024-reproduction",
        study_id=f"storm-freshwiki-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="storm",
            kind="research_agent",
            implementation="storm-wiki-paper-era",
            treatment="multi-perspective-question-asking",
            capabilities=(search_capability_id,),
            configurations=("storm.naacl2024.wiki-pipeline",),
        ),
        models={
            "perspective": StudyModel(
                "model.storm.perspective",
                prompt="storm.perspective.paper-era",
            ),
            "question": StudyModel(
                "model.storm.question",
                prompt="storm.question.paper-era",
            ),
            "expert": StudyModel(
                "model.storm.expert",
                prompt="storm.expert.paper-era",
            ),
            "outline": StudyModel(
                "model.storm.outline",
                prompt="storm.outline.paper-era",
            ),
            "article": StudyModel(
                "model.storm.article",
                prompt="storm.article.paper-era",
            ),
            "polish": StudyModel(
                "model.storm.polish",
                prompt="storm.polish.paper-era",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "heading_soft_recall",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="outline_heading_soft_recall",
                scale="continuous",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "heading_entity_recall",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="outline_heading_entity_recall",
                scale="continuous",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "rouge",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="article_rouge",
                scale="continuous",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "entity_recall",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="article_entity_recall",
                scale="continuous",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "rubric_score",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="article_rubric_quality",
                scale="continuous",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="freshwiki",
            ),
            MeasurementDefinition.scalar(
                "search_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="search_call",
                semantic_kind="retrieval_usage",
                scale="count",
                domain="freshwiki",
            ),
        ),
        trial=storm_freshwiki_trial_protocol(
            search_capability_id=search_capability_id,
        ),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "storm-freshwiki-paper-era",
            max_steps=256,
            max_model_calls=(
                1
                + fidelity.max_perspectives
                * fidelity.max_conversation_turns
                * 2
                + 3
            ),
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_storm_freshwiki_study",
    "storm_freshwiki_trial_protocol",
]
