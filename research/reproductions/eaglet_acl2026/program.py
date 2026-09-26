from __future__ import annotations

METHOD_ID="eaglet_acl2026"

PAPER_URI="https://aclanthology.org/2026.acl-long.597/"

BENCHMARK_IDS=("scienceworld", "alfworld", "webshop")

PROTOCOL=("reproduce teacher-plan synthesis and homologous consensus filtering", "perform SFT cold start before rule-based RL", "use executor capability gain rather than learned reward model", "report seen/unseen splits and training cost")

METRICS=("task_success", "seen_success", "unseen_success", "training_cost", "planner_tokens", "executor_capability_gain")

ABLATIONS=("without consensus filtering", "SFT-only", "without capability-gain reward", "implicit planning")

PHASES = (
    {
        "phase_id": 'plan_synthesis',
        "role": 'eaglet.teacher',
        "instruction": 'Synthesize candidate global plans with the teacher LLM.',
    },
    {
        "phase_id": 'consensus_filter',
        "role": 'eaglet.filter',
        "instruction": 'Apply homologous consensus filtering to retain high-quality plans.',
    },
    {
        "phase_id": 'cold_start_sft',
        "role": 'eaglet.training',
        "instruction": 'Fine-tune the planner on filtered plans for cold start.',
    },
    {
        "phase_id": 'capability_gain_rl',
        "role": 'eaglet.training',
        "instruction": 'Optimize with executor capability-gain reward without a learned reward model.',
    },
    {
        "phase_id": 'plan_execute',
        "role": 'eaglet.planner',
        "instruction": 'Generate a global plan and execute it with the downstream executor agent.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'eaglet_acl2026.phase-workflow.v1',
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
