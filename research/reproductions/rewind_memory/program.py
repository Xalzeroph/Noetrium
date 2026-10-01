from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'encode', 'role': 'rewind.visual', 'instruction': 'Encode sampled frames with the paper EVA-02 visual encoder semantics.', 'max_visits': 1},
    {'phase_id': 'write_memory', 'role': 'rewind.memory', 'instruction': 'Write two memory tokens per frame through the recurrent write-query path.', 'max_visits': 1},
    {'phase_id': 'instruction_select', 'role': 'rewind.selection', 'instruction': 'Run instruction-guided DFS selection over the completed video memory.', 'max_visits': 1},
    {'phase_id': 'cluster', 'role': 'rewind.selection', 'instruction': 'Apply DPC-KNN clustering to the selected frame/token candidates.', 'max_visits': 1},
    {'phase_id': 'read', 'role': 'rewind.memory', 'instruction': 'Read the compacted temporally ordered memory with the paper read queries.', 'max_visits': 1},
    {'phase_id': 'answer', 'role': 'rewind.reasoner', 'instruction': 'Generate the task answer from the selected memory and original visual features.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'rewind',
    "version": 'cvpr2025',
    "semantic_contract": 'rewind.memory.v2',
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
        evidence=('rewind' + ".phase-transcript", 'rewind' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('rewind' + "_trajectory",),
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
