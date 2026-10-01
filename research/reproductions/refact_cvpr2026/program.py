from __future__ import annotations

METHOD_ID="refact_cvpr2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html"

BENCHMARK_IDS=("groundedvqa",)

PROTOCOL=("reproduce GroundedVQA flexible-complexity evaluation", "preserve Grounding-tool calls and Defocus/Refocus memory operations", "compare on additional public agentic benchmarks from the final paper", "measure task quality against context density and visual-noise complexity")

METRICS=("answer_accuracy", "task_success", "grounding_accuracy", "context_tokens", "visual_focus_operations", "latency")

ABLATIONS=("without Grounding tool", "without Defocus/Refocus memory", "without active focusing")

PHASES = (
    {
        "phase_id": 'reason',
        "role": 'refact.reasoner',
        "instruction": 'Reason over the current multimodal web-search state.',
    },
    {
        "phase_id": 'ground_focus',
        "role": 'refact.grounding',
        "instruction": 'Actively ground and filter visual information relevant to the current reasoning step.',
    },
    {
        "phase_id": 'defocus_refocus',
        "role": 'refact.memory',
        "instruction": 'Use external-memory Defocus/Refocus operations to control retained context density.',
    },
    {
        "phase_id": 'act',
        "role": 'refact.agent',
        "instruction": 'Execute the next web-search or navigation action.',
    },
    {
        "phase_id": 'observe',
        "role": 'refact.agent',
        "instruction": 'Observe new multimodal evidence and update the working context.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'refact_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': 'CVPR 2026', 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=32)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
