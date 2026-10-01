from __future__ import annotations

METHOD_ID="mmbench_gui_cvpr2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html"

BENCHMARK_IDS=("mmbench-gui",)

PROTOCOL=("run all four hierarchy levels", "preserve six-platform evaluation across Windows/macOS/Linux/iOS/Android/Web", "report success and action redundancy jointly through EQA", "stratify complex and cross-application tasks")

METRICS=("content_understanding", "element_grounding", "task_success", "task_collaboration", "action_redundancy", "eqa")

ABLATIONS=("grounding-module analysis", "single-platform versus cross-platform", "quality-only versus EQA")

PHASES = (
    {
        "phase_id": 'content_understanding',
        "role": 'mmbench_gui.evaluator',
        "instruction": 'Evaluate GUI content understanding.',
    },
    {
        "phase_id": 'element_grounding',
        "role": 'mmbench_gui.evaluator',
        "instruction": 'Evaluate visual element grounding.',
    },
    {
        "phase_id": 'task_automation',
        "role": 'mmbench_gui.evaluator',
        "instruction": 'Evaluate end-to-end task automation.',
    },
    {
        "phase_id": 'task_collaboration',
        "role": 'mmbench_gui.evaluator',
        "instruction": 'Evaluate cross-application task collaboration.',
    },
    {
        "phase_id": 'eqa_score',
        "role": 'mmbench_gui.evaluator',
        "instruction": 'Compute Efficiency-Quality-Aware score from success and action redundancy.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'mmbench_gui_cvpr2026.phase-workflow.v1',
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
