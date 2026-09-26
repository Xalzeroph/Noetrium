from __future__ import annotations

METHOD_ID="ego2web_cvpr2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html"

BENCHMARK_IDS=("ego2web",)

PROTOCOL=("preserve human-verified video-task pairs and task categories", "evaluate video understanding, web planning and interaction jointly", "run final-paper task-design ablations", "validate automatic judge agreement against human labels")

METRICS=("task_success", "video_understanding", "web_execution_success", "judge_human_agreement", "steps", "latency")

ABLATIONS=("without video evidence", "weakened video understanding", "judge alternatives")

PHASES = (
    {
        "phase_id": 'video_understand',
        "role": 'ego2web.agent',
        "instruction": 'Extract task-relevant evidence from first-person video.',
    },
    {
        "phase_id": 'goal_ground',
        "role": 'ego2web.agent',
        "instruction": 'Ground the online task in observed physical-world evidence.',
    },
    {
        "phase_id": 'web_plan',
        "role": 'ego2web.agent',
        "instruction": 'Plan the required online workflow.',
    },
    {
        "phase_id": 'web_execute',
        "role": 'ego2web.agent',
        "instruction": 'Execute web actions under the frozen benchmark environment.',
    },
    {
        "phase_id": 'judge',
        "role": 'ego2web.judge',
        "instruction": 'Score completion with Ego2WebJudge and retain judge evidence.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'ego2web_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'CVPR 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=None)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
