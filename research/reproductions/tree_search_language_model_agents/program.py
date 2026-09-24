from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import (
    AgentMethodSpec,
    AgentPhaseSpec,
)

from .fidelity import TREE_SEARCH_VWA_FIDELITY


def build_tree_search_vwa_method_program():
    """Compile the released value-function tree-search loop into MethodProgram IR."""

    fidelity = TREE_SEARCH_VWA_FIDELITY
    phases = (
        AgentPhaseSpec(
            "reconstruct_parent",
            "tree-search.environment",
            "Open a fresh task session and replay the committed action prefix before "
            "evaluating a candidate branch.",
        ),
        AgentPhaseSpec(
            "expand",
            "tree-search.policy",
            "Generate at most the released branching-factor candidate browser actions "
            "from the current image-SOM observation.",
        ),
        AgentPhaseSpec(
            "evaluate",
            "tree-search.value",
            "Score candidate partial trajectories with the frozen value-function role "
            "under the released per-step evaluation budget.",
        ),
        AgentPhaseSpec(
            "select",
            "tree-search.search",
            "Select the best branch under the released value-function tree-search "
            "policy and bounded lookahead depth.",
        ),
        AgentPhaseSpec(
            "commit",
            "tree-search.policy",
            "Commit the selected browser action, retain the partial trajectory, and "
            "advance the authoritative environment state.",
        ),
    )
    return AgentMethodSpec(
        method_id="tree-search-language-model-agents",
        implementation_version="official-released-vwa-search",
        schema_version="tree-search-language-model-agents.vwa.method.v1",
        phases=phases,
        max_cycles=fidelity.max_steps,
        configuration={
            "source_lane_digest": fidelity.source.lane_digest,
            "benchmark": fidelity.benchmark,
            "site": fidelity.site,
            "agent_type": fidelity.agent_type,
            "search_algorithm": fidelity.search_algorithm,
            "policy_model_role": fidelity.policy_model,
            "value_model_role": fidelity.value_model,
            "evaluation_captioner_model": fidelity.evaluation_captioner_model,
            "max_steps": fidelity.max_steps,
            "max_depth": fidelity.max_depth,
            "lookahead_steps": fidelity.lookahead_steps,
            "branching_factor": fidelity.branching_factor,
            "value_function_budget": fidelity.value_function_budget,
            "environment_branch_strategy": fidelity.environment_branch_strategy,
            "observation_type": fidelity.observation_type,
            "action_set_tag": fidelity.action_set_tag,
            "prompt_path": fidelity.prompt_path,
        },
        evidence_obligations=(
            "tree-search.phase-transcript",
            "tree-search.model-receipts",
            "tree-search.environment-replay",
            "tree-search.value-evaluations",
            "tree-search.branch-selection",
        ),
        metric_names=(
            "task_score",
            "task_success",
            "committed_steps",
            "value_evaluations",
        ),
        artifact_kinds=(
            "tree_search_vwa_trajectory",
            "tree_search_vwa_search_tree",
        ),
    ).compile()


TREE_SEARCH_VWA_METHOD_PROGRAM = build_tree_search_vwa_method_program()


__all__ = [
    "TREE_SEARCH_VWA_METHOD_PROGRAM",
    "build_tree_search_vwa_method_program",
]
