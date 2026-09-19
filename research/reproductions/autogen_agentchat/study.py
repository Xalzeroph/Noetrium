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
from research.benchmarks.multiagentbench import MULTIAGENTBENCH_BENCHMARK_ID

from .fidelity import AUTOGEN_AGENTCHAT_FIDELITY
from .program import build_autogen_groupchat_method_program


def autogen_multiagentbench_trial_protocol(
    participant_ids: tuple[str, ...],
) -> ExperimentTrialProtocolIdentity:
    program = build_autogen_groupchat_method_program(participant_ids)
    return ExperimentTrialProtocolIdentity(
        "autogen.paper-era.multiagentbench.v1",
        canonical_digest(
            {
                "program_digest": program.program_digest,
                "source_commit": AUTOGEN_AGENTCHAT_FIDELITY.audited_commit,
                "participant_ids": participant_ids,
                "max_round": AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round,
                "broadcast_excludes_speaker": (
                    AUTOGEN_AGENTCHAT_FIDELITY.groupchat_broadcast_excludes_speaker
                ),
                "speaker_fallback_round_robin": (
                    AUTOGEN_AGENTCHAT_FIDELITY.invalid_or_failed_speaker_selection_falls_back_round_robin
                ),
                "admin_takeover": AUTOGEN_AGENTCHAT_FIDELITY.admin_can_take_over_on_interrupt,
            }
        ),
    )


def build_autogen_multiagentbench_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
    participant_ids: tuple[str, ...] = ("agent1", "agent2", "user_proxy"),
) -> ResearchStudyDefinition:
    program = build_autogen_groupchat_method_program(participant_ids)
    if benchmark.benchmark_id != MULTIAGENTBENCH_BENCHMARK_ID:
        raise ValueError("AutoGen GroupChat study requires MultiAgentBench")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("AutoGen MultiAgentBench study requires a non-empty split")

    participants = tuple(
        StudyParticipant(
            role=participant_id,
            kind="human_proxy" if participant_id == "user_proxy" else "agent",
            implementation=(
                "autogen-user-proxy-paper-era"
                if participant_id == "user_proxy"
                else "autogen-conversable-agent-paper-era"
            ),
            treatment="paper-era-groupchat",
            capabilities=(
                ("software.command",)
                if participant_id == "user_proxy"
                else ()
            ),
            configurations=(f"autogen.{participant_id}.configuration",),
            depends_on=("manager",),
        )
        for participant_id in participant_ids
    )
    models: dict[str, StudyModel] = {
        "manager": StudyModel(
            "model.autogen.speaker-selector",
            prompt="autogen.groupchat.manager.prompt",
        )
    }
    for participant_id in participant_ids:
        models[participant_id] = StudyModel(
            f"model.autogen.{participant_id}",
            prompt=f"autogen.{participant_id}.prompt",
            required=participant_id != "user_proxy",
            max_bindings=1,
        )

    return Study(
        project_id="autogen-paper-era-reproduction",
        study_id=f"autogen-paper-era-multiagentbench-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="manager",
            kind="coordinator",
            implementation="autogen-paper-era-groupchat",
            treatment="paper-era-groupchat",
            configurations=("autogen.groupchat.manager",),
        ),
        participants=participants,
        models=models,
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="multiagentbench",
            ),
            MeasurementDefinition.scalar(
                "round_count",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="interaction_length",
                scale="count",
                domain="multiagentbench",
            ),
            MeasurementDefinition.scalar(
                "message_count",
                schema_id="noetrium.measurement.count.v1",
                unit="message",
                semantic_kind="communication_usage",
                scale="count",
                domain="multiagentbench",
            ),
            MeasurementDefinition.scalar(
                "speaker_fallback_count",
                schema_id="noetrium.measurement.count.v1",
                unit="fallback",
                semantic_kind="coordination_recovery",
                scale="count",
                domain="multiagentbench",
            ),
            MeasurementDefinition.scalar(
                "interrupt_count",
                schema_id="noetrium.measurement.count.v1",
                unit="interrupt",
                semantic_kind="human_interaction",
                scale="count",
                domain="multiagentbench",
            ),
        ),
        trial=autogen_multiagentbench_trial_protocol(participant_ids),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "autogen-paper-era-groupchat",
            max_steps=256,
            max_turns=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round,
            max_messages=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round,
            max_model_calls=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round * 2,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "autogen_multiagentbench_trial_protocol",
    "build_autogen_multiagentbench_study",
]
