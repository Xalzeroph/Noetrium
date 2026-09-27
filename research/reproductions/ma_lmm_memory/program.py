from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'encode_frame', 'role': 'ma_lmm.visual', 'instruction': 'Encode incoming video frames and append visual tokens with position information.', 'max_visits': 1},
    {'phase_id': 'compress_visual_bank', 'role': 'ma_lmm.memory', 'instruction': 'Compress adjacent visual-memory entries by per-token cosine similarity and size-weighted merge.', 'max_visits': 1},
    {'phase_id': 'update_query_bank', 'role': 'ma_lmm.query', 'instruction': 'Update recurrent query memory used as attention keys and values.', 'max_visits': 1},
    {'phase_id': 'answer', 'role': 'ma_lmm.reasoner', 'instruction': 'Answer the LVU task from the bounded visual and query memory banks.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'ma-lmm',
    "version": 'cvpr2024',
    "semantic_contract": 'ma-lmm.memory.v2',
    "entrypoint": METHOD_PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({
        "paper_revision": REPRODUCTION.identity.paper_revision,
        "benchmark_ids": REPRODUCTION.catalog.benchmark_ids,
        "method_owned": REPRODUCTION.catalog.method_owned,
        "architecture": "method-owned-components-on-shared-machine-kernel",
    })
    method.policy(
        execution="effect_recorded",
        evidence=('ma-lmm' + ".phase-transcript", 'ma-lmm' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('ma-lmm' + "_trajectory",),
    )
    method.phases(METHOD_PHASES, max_cycles=None)
    return method

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = (
    "METHOD_SPEC", "METHOD_PHASES", "configure_method", "METHOD_CONFIGURER",
    "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS",
)
