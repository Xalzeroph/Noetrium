from __future__ import annotations

METHOD_ID="orbit_acl2026"

PAPER_URI="https://aclanthology.org/2026.acl-long.1822/"

BENCHMARK_IDS=("embodiedbench",)

PROTOCOL=("separate on-policy trajectory collection from offline reward computation", "evaluate in-domain and out-of-domain EmbodiedBench settings", "hold interaction budget fixed across RL baselines", "preserve visual observations and multi-step action semantics")

METRICS=("task_success", "in_domain_success", "out_of_domain_success", "reward", "interaction_cost", "training_cost")

ABLATIONS=("without offline reward", "off-policy-only training", "without reinforcement fine-tuning")

PHASES = (
    {
        "phase_id": 'collect_onpolicy',
        "role": 'orbit.policy',
        "instruction": 'Collect on-policy multi-step embodied planning trajectories.',
    },
    {
        "phase_id": 'offline_reward',
        "role": 'orbit.reward',
        "instruction": "Score collected trajectories with the paper's offline reward mechanism.",
    },
    {
        "phase_id": 'reinforcement_update',
        "role": 'orbit.training',
        "instruction": 'Apply reinforcement fine-tuning using offline reward.',
    },
    {
        "phase_id": 'evaluate_id',
        "role": 'orbit.evaluator',
        "instruction": 'Evaluate in-domain EB-ALFRED tasks.',
    },
    {
        "phase_id": 'evaluate_ood',
        "role": 'orbit.evaluator',
        "instruction": 'Evaluate unseen EB-Habitat tasks.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'orbit_acl2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'ACL 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
