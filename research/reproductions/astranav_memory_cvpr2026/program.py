from __future__ import annotations

METHOD_ID="astranav_memory_cvpr2026"

TITLE="AstraNav-Memory: Contexts Compression for Long Memory"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Hu_AstraNav-Memory_Contexts_Compression_for_Long_Memory_CVPR_2026_paper.html"

BENCHMARK_IDS=("goat-bench", "hm3d-ovon")

PROTOCOL=("evaluate GOAT-Bench and HM3D-OVON separately", "reproduce configurable visual compression ratios", "retain hundreds of historical frames in-context without object-centric reconstruction", "report unfamiliar-environment exploration and familiar-environment path efficiency")

METRICS=("navigation_success", "spl", "visual_tokens_per_frame", "compression_ratio", "history_frame_count", "path_length")

ABLATIONS=("without long-term visual context", "low compression", "excessive compression", "object-centric memory baseline")

PHASES = (
    {
        "phase_id": 'observe',
        "role": 'astranav.agent',
        "instruction": 'Acquire the current navigation image and task context.',
    },
    {
        "phase_id": 'compress_visual',
        "role": 'astranav.memory',
        "instruction": 'Compress the image through frozen DINOv3 features plus PixelUnshuffle/Conv visual tokenizer.',
    },
    {
        "phase_id": 'append_context',
        "role": 'astranav.memory',
        "instruction": 'Append compressed image tokens to the long-horizon image-centric memory context.',
    },
    {
        "phase_id": 'reason_navigation',
        "role": 'astranav.policy',
        "instruction": 'Reason over current and historical compressed visual contexts with Qwen2.5-VL.',
    },
    {
        "phase_id": 'act',
        "role": 'astranav.policy',
        "instruction": 'Execute the next navigation action and preserve trajectory evidence.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'astranav_memory_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=256)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
