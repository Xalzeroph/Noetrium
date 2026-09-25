from __future__ import annotations

from noetrium.api import (
    AgentMethodSpec,
    AgentPhaseSpec,
)

from .fidelity import EXACT_VWA_FIDELITY


def build_exact_vwa_method_program():
    """Compile the released ExACT VWA R-MCTS semantics into canonical MethodProgram IR."""

    fidelity = EXACT_VWA_FIDELITY
    phases = (
        AgentPhaseSpec(
            "reconstruct_parent",
            "exact.environment",
            "Reset the browser task and replay the committed action history before "
            "evaluating a new search branch. Preserve replay receipts as evidence.",
        ),
        AgentPhaseSpec(
            "expand_policy",
            "exact.policy",
            "Generate the bounded Reflective-MCTS candidate action set from the "
            "current image-SOM observation and accumulated reflections.",
        ),
        AgentPhaseSpec(
            "debate_value",
            "exact.value",
            "Evaluate candidate branches with the released multi-agent debate value "
            "function under the exact value-function budget.",
        ),
        AgentPhaseSpec(
            "puct_select",
            "exact.search",
            "Select the next branch/action using the released PUCT search rule and "
            "bounded search depth.",
        ),
        AgentPhaseSpec(
            "commit_action",
            "exact.policy",
            "Commit the selected browser action to the authoritative environment "
            "trajectory and record the resulting observation.",
        ),
        AgentPhaseSpec(
            "contrastive_reflect",
            "exact.reflection",
            "When the released reflection threshold is met, construct contrastive "
            "reflection from explored alternatives and feed it into later policy steps.",
        ),
    )
    return AgentMethodSpec(
        method_id="exact",
        implementation_version="vwa-later-released-protocol",
        schema_version="exact.vwa.reflective-mcts.method.v1",
        phases=phases,
        max_cycles=fidelity.max_environment_steps,
        configuration={
            "source_lane_digest": fidelity.source.lane_digest,
            "agent_type": fidelity.agent_type,
            "benchmark_site": fidelity.benchmark_site,
            "observation_type": fidelity.observation_type,
            "action_set_tag": fidelity.action_set_tag,
            "environment_branch_strategy": fidelity.environment_branch_strategy,
            "max_depth": fidelity.max_depth,
            "lookahead_steps": fidelity.lookahead_steps,
            "branching_factor": fidelity.branching_factor,
            "value_function_budget": fidelity.value_function_budget,
            "puct": fidelity.puct,
            "max_reflections_per_task": fidelity.max_reflections_per_task,
            "reflection_threshold": fidelity.reflection_threshold,
            "value_function_method": fidelity.value_function_method,
            "value_max_reflections_per_task": (
                fidelity.value_max_reflections_per_task
            ),
            "value_reflection_threshold": fidelity.value_reflection_threshold,
            "policy_model_role": fidelity.policy_model,
            "value_model_role": fidelity.value_model,
            "reflective_model_role": fidelity.reflective_language_model,
            "embedding_model_role": fidelity.embedding_model,
        },
        evidence_obligations=(
            "exact.phase-transcript",
            "exact.model-receipts",
            "exact.environment-replay",
            "exact.search-decision",
            "exact.reflection",
        ),
        metric_names=("task_success", "environment_steps"),
        artifact_kinds=(
            "exact_vwa_trajectory",
            "exact_vwa_search_tree",
            "exact_vwa_reflections",
        ),
    ).compile()


EXACT_VWA_METHOD_PROGRAM = build_exact_vwa_method_program()


__all__ = [
    "EXACT_VWA_METHOD_PROGRAM",
    "build_exact_vwa_method_program",
]
