from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="astranav_memory_cvpr2026"
TITLE="AstraNav-Memory: Contexts Compression for Long Memory"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Hu_AstraNav-Memory_Contexts_Compression_for_Long_Memory_CVPR_2026_paper.html"
BENCHMARK_IDS=("goat-bench", "hm3d-ovon")
PROTOCOL=("evaluate GOAT-Bench and HM3D-OVON separately", "reproduce configurable visual compression ratios", "retain hundreds of historical frames in-context without object-centric reconstruction", "report unfamiliar-environment exploration and familiar-environment path efficiency")
METRICS=("navigation_success", "spl", "visual_tokens_per_frame", "compression_ratio", "history_frame_count", "path_length")
ABLATIONS=("without long-term visual context", "low compression", "excessive compression", "object-centric memory baseline")
PHASES=(
    AgentPhaseSpec("observe", "astranav.agent", "Acquire the current navigation image and task context."),
    AgentPhaseSpec("compress_visual", "astranav.memory", "Compress the image through frozen DINOv3 features plus PixelUnshuffle/Conv visual tokenizer."),
    AgentPhaseSpec("append_context", "astranav.memory", "Append compressed image tokens to the long-horizon image-centric memory context."),
    AgentPhaseSpec("reason_navigation", "astranav.policy", "Reason over current and historical compressed visual contexts with Qwen2.5-VL."),
    AgentPhaseSpec("act", "astranav.policy", "Execute the next navigation action and preserve trajectory evidence."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="astranav_memory_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=256,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
