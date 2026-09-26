from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.multiagentbench import MULTIAGENTBENCH_BENCHMARK_ID

from .fidelity import AUTOGEN_AGENTCHAT_FIDELITY
from .program import build_autogen_groupchat_method_program


def autogen_multiagentbench_trial_protocol(
    participant_ids: tuple[str, ...],
):
    program = build_autogen_groupchat_method_program(participant_ids)
    return _rs.study_protocol(
        "autogen.paper-era.multiagentbench.v1",
        _rs.canonical_digest(
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


@_rs.study_factory('benchmark')
def build_autogen_multiagentbench_study(
    benchmark,
    *,
    split_id: str,
    participant_ids: tuple[str, ...] = ("agent1", "agent2", "user_proxy"),
):
    program = build_autogen_groupchat_method_program(participant_ids)
    if benchmark.benchmark_id != MULTIAGENTBENCH_BENCHMARK_ID:
        raise ValueError("AutoGen GroupChat study requires MultiAgentBench")
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("AutoGen MultiAgentBench study requires a non-empty split")

    participants = tuple(
        _rs.study_participant(
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
    models: dict[str, object] = {
        "manager": _rs.study_model(
            "model.autogen.speaker-selector",
            prompt="autogen.groupchat.manager.prompt",
        )
    }
    for participant_id in participant_ids:
        models[participant_id] = _rs.study_model(
            f"model.autogen.{participant_id}",
            prompt=f"autogen.{participant_id}.prompt",
            required=participant_id != "user_proxy",
            max_bindings=1,
        )

    return _rs.study_spec(project_id="autogen-paper-era-reproduction",
        study_id=f"autogen-paper-era-multiagentbench-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=_rs.study_participant(
            role="manager",
            kind="coordinator",
            implementation="autogen-paper-era-groupchat",
            treatment="paper-era-groupchat",
            configurations=("autogen.groupchat.manager",),
        ),
        participants=participants,
        models=models,
        measurements=(
            _rs.scalar_measurement(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="multiagentbench",
            ),
            _rs.scalar_measurement(
                "round_count",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="interaction_length",
                scale="count",
                domain="multiagentbench",
            ),
            _rs.scalar_measurement(
                "message_count",
                schema_id="noetrium.measurement.count.v1",
                unit="message",
                semantic_kind="communication_usage",
                scale="count",
                domain="multiagentbench",
            ),
            _rs.scalar_measurement(
                "speaker_fallback_count",
                schema_id="noetrium.measurement.count.v1",
                unit="fallback",
                semantic_kind="coordination_recovery",
                scale="count",
                domain="multiagentbench",
            ),
            _rs.scalar_measurement(
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
        limits=_rs.trial_budget(
            "autogen-paper-era-groupchat",
            max_steps=256,
            max_turns=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round,
            max_messages=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round,
            max_model_calls=AUTOGEN_AGENTCHAT_FIDELITY.groupchat_default_max_round * 2,
            max_working_seconds=3600.0,
        ),
        replay_level='observational',
    )


__all__ = [
    "autogen_multiagentbench_trial_protocol",
    "build_autogen_multiagentbench_study",
]
