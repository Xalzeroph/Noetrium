from __future__ import annotations

METHOD_ID="crossha_cvpr2026"

TITLE="Training One Model to Master Cross-Level Agentic Actions via Reinforcement Learning"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/He_Training_One_Model_to_Master_Cross-Level_Agentic_Actions_via_Reinforcement_CVPR_2026_paper.html"

BENCHMARK_IDS=("minecraft-openha",)

PROTOCOL=("perform cold-start supervised fine-tuning before multi-turn GRPO", "preserve the mixed heterogeneous action space rather than fixed single-space policies", "evaluate 800+ OpenHA tasks across Mine Blocks, Kill Entities and Craft Items", "report finished-task coverage and average success rate per category")

METRICS=("finished_tasks", "average_success_rate", "mine_success", "kill_success", "craft_success", "steps", "action_space_switch_count")

ABLATIONS=("without multi-turn GRPO", "grounding-only action space", "motion-only action space", "fixed action interface")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'crossha.policy',
        "instruction": 'Observe the Minecraft RGB stream, task instruction and recent trajectory context without privileged state.',
    },
    {
        "phase_id": 'select_action_space',
        "role": 'crossha.policy',
        "instruction": 'Choose the most suitable action interface and granularity for the current step.',
    },
    {
        "phase_id": 'instantiate_action',
        "role": 'crossha.policy',
        "instruction": 'Generate a motion-, grounding-, or text-level action under the selected interface.',
    },
    {
        "phase_id": 'execute',
        "role": 'crossha.environment',
        "instruction": 'Execute the human-like mouse/keyboard interaction in Minecraft 1.16.5.',
    },
    {
        "phase_id": 'score_rollout',
        "role": 'crossha.training',
        "instruction": 'Collect multi-turn task reward used by Group Relative Policy Optimization.',
    },
    {
        "phase_id": 'policy_update',
        "role": 'crossha.training',
        "instruction": 'Update the unified policy with multi-turn GRPO while preserving heterogeneous action switching.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'crossha_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=200)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
