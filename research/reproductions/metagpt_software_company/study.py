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
from research.benchmarks.humaneval import (
    HUMANEVAL_BENCHMARK_ID,
    HUMANEVAL_SPLIT_ID,
)

from .fidelity import METAGPT_SOFTWARE_COMPANY_FIDELITY
from .program import build_metagpt_software_company_method_program

_ARTIFACT_CAPABILITY = "artifact.publish"


def metagpt_humaneval_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    use_code_review: bool,
) -> ExperimentTrialProtocolIdentity:
    if benchmark.benchmark_id != HUMANEVAL_BENCHMARK_ID:
        raise ValueError("MetaGPT formal coding protocol requires HumanEval")
    selected = benchmark.selected_tasks(HUMANEVAL_SPLIT_ID)
    if len(selected) != 164:
        raise ValueError("MetaGPT HumanEval protocol requires the full 164-task cut")
    program = build_metagpt_software_company_method_program(
        use_code_review=use_code_review,
    )
    return ExperimentTrialProtocolIdentity(
        (
            "metagpt.iclr-2024.humaneval.code-review.v1"
            if use_code_review
            else "metagpt.iclr-2024.humaneval.core-sop.v1"
        ),
        canonical_digest(
            {
                "program_digest": program.program_digest,
                "source_commit": METAGPT_SOFTWARE_COMPANY_FIDELITY.audited_commit,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(task.task_id for task in selected),
                "core_roles": METAGPT_SOFTWARE_COMPANY_FIDELITY.core_roles,
                "sop_edges": METAGPT_SOFTWARE_COMPANY_FIDELITY.sop_edges,
                "use_code_review": use_code_review,
                "artifact_publication": "immutable_content_addressed",
            }
        ),
    )


def build_metagpt_humaneval_study(
    benchmark: BenchmarkTaskSet,
    *,
    use_code_review: bool = False,
) -> ResearchStudyDefinition:
    protocol = metagpt_humaneval_trial_protocol(
        benchmark,
        use_code_review=use_code_review,
    )
    treatment = "paper-era-sop+code-review" if use_code_review else "paper-era-sop"
    participants = (
        StudyParticipant(
            role="metagpt.product-manager",
            kind="agent",
            implementation="metagpt-product-manager-paper-era",
            treatment=treatment,
            configurations=("metagpt.write-prd",),
            depends_on=("software_company",),
        ),
        StudyParticipant(
            role="metagpt.architect",
            kind="agent",
            implementation="metagpt-architect-paper-era",
            treatment=treatment,
            configurations=("metagpt.write-design",),
            depends_on=("metagpt.product-manager",),
        ),
        StudyParticipant(
            role="metagpt.project-manager",
            kind="agent",
            implementation="metagpt-project-manager-paper-era",
            treatment=treatment,
            configurations=("metagpt.write-tasks",),
            depends_on=("metagpt.architect",),
        ),
        StudyParticipant(
            role="metagpt.engineer",
            kind="agent",
            implementation="metagpt-engineer-paper-era",
            treatment=treatment,
            configurations=(
                ("metagpt.write-code", "metagpt.write-code-review")
                if use_code_review
                else ("metagpt.write-code",)
            ),
            depends_on=("metagpt.project-manager",),
        ),
    )
    models = {
        role: StudyModel(
            f"model.{role}",
            prompt=f"{role}.{treatment}.prompt",
        )
        for role in (
            "metagpt.product-manager",
            "metagpt.architect",
            "metagpt.project-manager",
            "metagpt.engineer",
        )
    }

    return Study(
        project_id="metagpt-iclr-2024-reproduction",
        study_id=f"metagpt-human-eval-{treatment}",
        benchmark=benchmark,
        benchmark_split_id=HUMANEVAL_SPLIT_ID,
        method=StudyParticipant(
            role="software_company",
            kind="method",
            implementation="metagpt-software-company-paper-era",
            treatment=treatment,
            capabilities=(_ARTIFACT_CAPABILITY,),
            configurations=("metagpt.software-company.sop",),
        ),
        participants=participants,
        models=models,
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="pass_at_1",
                scale="binary",
                domain="humaneval",
            ),
            MeasurementDefinition.scalar(
                "artifact_count",
                schema_id="noetrium.measurement.count.v1",
                unit="artifact",
                semantic_kind="sop_artifact_usage",
                scale="count",
                domain="metagpt",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="metagpt",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            f"metagpt-human-eval-{treatment}",
            max_steps=64,
            max_turns=5 if use_code_review else 4,
            max_model_calls=5 if use_code_review else 4,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_metagpt_humaneval_study",
    "metagpt_humaneval_trial_protocol",
]
