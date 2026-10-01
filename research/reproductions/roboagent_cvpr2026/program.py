from __future__ import annotations

METHOD_ID="roboagent_cvpr2026"

TITLE="RoboAgent: Chaining Basic Capabilities for Embodied Task Planning"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Xu_RoboAgent_Chaining_Basic_Capabilities_for_Embodied_Task_Planning_CVPR_2026_paper.html"

BENCHMARK_IDS=("alfworld", "embodiedbench")

PROTOCOL=("reproduce behavior-cloning warm start from expert plans", "reproduce DAgger trajectory collection using the current model", "reproduce expert-policy-guided reinforcement learning", "evaluate ALFWorld visual/text settings and EB-ALFRED separately")

METRICS=("task_success", "seen_success", "unseen_success", "capability_calls", "steps", "planning_efficiency")

ABLATIONS=("without capability-private contexts", "without DAgger", "without reinforcement learning", "monolithic planner without scheduler")

PHASES = (
    {
        "phase_id": 'scheduler',
        "role": 'roboagent.scheduler',
        "instruction": 'Decompose the current embodied task and route the next query to a basic capability.',
    },
    {
        "phase_id": 'capability_context',
        "role": 'roboagent.capability',
        "instruction": "Load the selected capability's private context rather than a monolithic global history.",
    },
    {
        "phase_id": 'capability_reason',
        "role": 'roboagent.capability',
        "instruction": 'Solve the routed vision-language subproblem with the shared VLM.',
    },
    {
        "phase_id": 'environment_interact',
        "role": 'roboagent.executor',
        "instruction": 'Execute an atomic embodied action when the selected capability requires environment interaction.',
    },
    {
        "phase_id": 'return_intermediate',
        "role": 'roboagent.scheduler',
        "instruction": 'Return the capability result to the scheduler and update the high-level plan.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'roboagent_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=64)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
