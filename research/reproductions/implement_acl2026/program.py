from __future__ import annotations

METHOD_ID="implement_acl2026"

PAPER_URI="https://aclanthology.org/2026.acl-long.827/"

BENCHMARK_IDS=("alfworld",)

PROTOCOL=("keep the policy LLM frozen during imaginative planning", "reproduce Monte Carlo future-state prediction by temperature sampling", "reproduce Meta In-Context Learning world-model adaptation", "report success over 1, 6, and 12 trials on held-out ALFWorld tasks")

METRICS=("task_success", "planning_accuracy", "world_model_prediction", "imagined_rollouts", "steps", "model_calls")

ABLATIONS=("without world model", "single deterministic future", "without Meta-ICL", "without online policy refinement")

PHASES = (
    {
        "phase_id": 'perceive_symbolic',
        "role": 'implement.world_model',
        "instruction": 'Convert raw visual observations into object-centric symbolic states.',
    },
    {
        "phase_id": 'propose_actions',
        "role": 'implement.llm',
        "instruction": 'Propose candidate actions from current symbolic state and task goal.',
    },
    {
        "phase_id": 'imagine_futures',
        "role": 'implement.world_model',
        "instruction": 'Predict Monte Carlo future states for candidate actions using temperature sampling.',
    },
    {
        "phase_id": 'rank_refine',
        "role": 'implement.llm',
        "instruction": 'Rank imagined trajectories and refine the decision.',
    },
    {
        "phase_id": 'execute',
        "role": 'implement.agent',
        "instruction": 'Execute the selected action in ALFWorld.',
    },
    {
        "phase_id": 'meta_icl_update',
        "role": 'implement.world_model',
        "instruction": 'Condition the world model on new interaction history for unseen-environment adaptation.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'implement_acl2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'ACL 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=64)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
