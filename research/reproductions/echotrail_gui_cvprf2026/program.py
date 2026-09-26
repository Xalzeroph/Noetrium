from __future__ import annotations

METHOD_ID="echotrail_gui_cvprf2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html"

BENCHMARK_IDS=("androidworld", "androidlab")

PROTOCOL=("construct the memory database only from autonomous critic-validated successes", "freeze retrieval policy and memory injection format", "compare before and after memory injection on AndroidWorld and AndroidLab", "report operational efficiency together with task success")

METRICS=("task_success_rate", "steps", "trajectory_acceptance", "memory_retrieval_hit", "token_cost")

ABLATIONS=("without critic validation", "without memory retrieval", "random trajectory injection")

PHASES = (
    {
        "phase_id": 'explore',
        "role": 'echotrail.explorer',
        "instruction": 'Autonomously explore GUI tasks and collect candidate successful trajectories.',
    },
    {
        "phase_id": 'critic_validate',
        "role": 'echotrail.critic',
        "instruction": 'Validate explored trajectories with the reward/critic model.',
    },
    {
        "phase_id": 'store_memory',
        "role": 'echotrail.memory',
        "instruction": 'Store critic-validated successful trajectories as actionable memories.',
    },
    {
        "phase_id": 'retrieve_memory',
        "role": 'echotrail.memory',
        "instruction": 'Retrieve relevant prior trajectories for a new GUI task.',
    },
    {
        "phase_id": 'guided_inference',
        "role": 'echotrail.agent',
        "instruction": 'Inject retrieved trajectories as in-context guidance and execute the task.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'echotrail_gui_cvprf2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'CVPR Findings 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
