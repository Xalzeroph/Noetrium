from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'short_memory', 'role': 'moviechat.memory', 'instruction': 'Accumulate the FIFO short-term token memory for the current video fragment.', 'max_visits': 1},
    {'phase_id': 'merge_short', 'role': 'moviechat.memory', 'instruction': 'Select the most similar short-memory pair and merge it before long-memory transfer.', 'max_visits': 1},
    {'phase_id': 'update_long', 'role': 'moviechat.memory', 'instruction': 'Append compressed short memory to long memory and enforce the released long-memory policy.', 'max_visits': 1},
    {'phase_id': 'retrieve', 'role': 'moviechat.memory', 'instruction': 'Construct global or breakpoint memory context using the paper retrieval semantics.', 'max_visits': 1},
    {'phase_id': 'answer', 'role': 'moviechat.reasoner', 'instruction': 'Generate the video QA answer from the selected memory context.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'moviechat',
    "version": 'cvpr2024',
    "semantic_contract": 'moviechat.memory.v2',
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
        evidence=('moviechat' + ".phase-transcript", 'moviechat' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('moviechat' + "_trajectory",),
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
