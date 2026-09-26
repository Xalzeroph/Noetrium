from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.srdd import (
    SRDD_BENCHMARK_ID,
    SRDD_SPLIT_ID,
    SRDD_TASK_COUNT,
)

from .fidelity import CHATDEV_V1_REFERENCE_FIDELITY
from .program import CHATDEV_V1_CHAIN_DIGEST, CHATDEV_V1_METHOD_PROGRAM


def chatdev_acl2024_srdd_trial_protocol(
    benchmark,
):
    if benchmark.benchmark_id != SRDD_BENCHMARK_ID:
        raise ValueError("ChatDev v1 protocol requires SRDD")
    selected = benchmark.selected_tasks(SRDD_SPLIT_ID)
    if len(selected) != SRDD_TASK_COUNT:
        raise ValueError("ChatDev v1 SRDD protocol requires 1200 tasks")
    fidelity = CHATDEV_V1_REFERENCE_FIDELITY
    return _rs.study_protocol(
        "chatdev.acl2024.srdd.v1.0.0.protocol-bound.v1",
        _rs.canonical_digest(
            {
                "source_commit": fidelity.audited_commit,
                "method_program_digest": CHATDEV_V1_METHOD_PROGRAM.program_digest,
                "chain_digest": CHATDEV_V1_CHAIN_DIGEST,
                "benchmark_cut_digest": benchmark.cut_digest,
                "task_ids": tuple(row.task_id for row in selected),
                "top_level_phase_order": fidelity.top_level_phase_order,
                "reflection_phases": fidelity.reflection_phases,
                "reflection_roles": fidelity.reflection_roles,
                "default_chat_turn_limit": fidelity.default_chat_turn_limit,
                "code_complete_cycle_limit": fidelity.code_complete_cycle_limit,
                "code_review_cycle_limit": fidelity.code_review_cycle_limit,
                "test_cycle_limit": fidelity.test_cycle_limit,
                "clear_structure": fidelity.clear_structure,
                "gui_design": fidelity.gui_design,
                "historical_model_binding": "unresolved-hosted-paper-era-service",
            }
        ),
    )


@_rs.study_factory('benchmark')
def build_chatdev_acl2024_srdd_study(
    benchmark,
):
    protocol = chatdev_acl2024_srdd_trial_protocol(benchmark)
    return _rs.study_spec(project_id="chatdev-acl-2024-reproduction",
        study_id="chatdev-acl-2024-srdd-v1.0.0",
        benchmark=benchmark,
        benchmark_split_id=SRDD_SPLIT_ID,
        method=_rs.study_participant(
            role="communicative_software_company",
            kind="multi_agent_method",
            implementation="chatdev-v1.0.0",
            treatment="acl-2024-paper-release",
            capabilities=("software.repository",),
            configurations=(
                "chatdev.v1.default-chat-chain",
                "chatdev.v1.role-specialization",
                "chatdev.v1.composed-phase-loops",
                "chatdev.v1.reflection-phases",
            ),
        ),
        models={},
        measurements=(
            _rs.scalar_measurement(
                "completeness",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="srdd_software_completeness",
                scale="continuous",
                domain="srdd",
            ),
            _rs.scalar_measurement(
                "executability",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="srdd_software_executability",
                scale="continuous",
                domain="srdd",
            ),
            _rs.scalar_measurement(
                "consistency",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="srdd_software_consistency",
                scale="continuous",
                domain="srdd",
            ),
            _rs.scalar_measurement(
                "quality",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="srdd_software_quality",
                scale="continuous",
                domain="srdd",
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("paper-service-default",),
        limits=_rs.trial_budget(
            "chatdev-acl2024-srdd-safety",
            max_steps=1024,
            max_turns=512,
            max_model_calls=1024,
            max_working_seconds=7200.0,
        ),
        replay_level='observational',
        repetition_timeout_seconds=7200.0,
    )


__all__ = [
    "build_chatdev_acl2024_srdd_study",
    "chatdev_acl2024_srdd_trial_protocol",
]
