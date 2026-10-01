from __future__ import annotations

METHOD_ID="vilomem_cvpr2026"

TITLE="ViLoMem: Agentic Learner with Grow-and-Refine Multimodal Semantic Memory"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Bo_ViLoMem_Agentic_Learner_with_Grow-and-Refine_Multimodal_Semantic_Memory_CVPR_2026_paper.html"

BENCHMARK_IDS=("mmmu", "mathvista", "mathvision", "hallusionbench", "mmstar", "realworldqa")

PROTOCOL=("evaluate the six final-paper multimodal reasoning benchmarks under matched backbone/model settings", "separate logical-memory and visual-memory generation/retrieval paths", "preserve grow-versus-refine merge semantics and verifier filtering", "run cross-benchmark memory generalization and cross-model memory transfer separately")

METRICS=("pass_at_1", "logic_error_repeat_rate", "visual_error_repeat_rate", "memory_schema_count", "retrieval_hit_rate", "memory_tokens")

ABLATIONS=("without visual memory", "without logical memory", "without distraction-hallucination separation", "without grow-and-refine merging", "cross-benchmark memory only")

PHASES = (
    {
        "phase_id": 'solve',
        "role": 'vilomem.solver',
        "instruction": 'Solve the multimodal query using retrieved logical and visual semantic memories.',
    },
    {
        "phase_id": 'verify',
        "role": 'vilomem.verifier',
        "instruction": 'Verify the prediction and identify whether the attempt should contribute new memory.',
    },
    {
        "phase_id": 'attribute_logic_error',
        "role": 'vilomem.logic_memory',
        "instruction": 'Attribute reasoning failures into structured logical error and strategy schemas.',
    },
    {
        "phase_id": 'attribute_visual_error',
        "role": 'vilomem.visual_memory',
        "instruction": 'Analyze attention/perception failures and isolate visual distraction or hallucination patterns.',
    },
    {
        "phase_id": 'grow_or_refine',
        "role": 'vilomem.memory',
        "instruction": 'Merge with a similar memory schema or create a new schema while preserving stable reusable knowledge.',
    },
    {
        "phase_id": 'dual_retrieve',
        "role": 'vilomem.retriever',
        "instruction": 'Retrieve logical memories by problem/text similarity and visual memories by image embedding plus query filtering.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'vilomem_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=8)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
