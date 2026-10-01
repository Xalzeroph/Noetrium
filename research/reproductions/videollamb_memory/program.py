from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'segment', 'role': 'videollamb.visual', 'instruction': 'Process the next video segment into visual tokens.', 'max_visits': 1},
    {'phase_id': 'bridge', 'role': 'videollamb.memory', 'instruction': 'Propagate recurrent memory tokens through the memory bridge layer.', 'max_visits': 1},
    {'phase_id': 'cache', 'role': 'videollamb.memory', 'instruction': 'Update the bounded memory cache used for later retrieval.', 'max_visits': 1},
    {'phase_id': 'retrieve', 'role': 'videollamb.memory', 'instruction': 'Retrieve scene-aware memory with the released tiling semantics.', 'max_visits': 1},
    {'phase_id': 'answer', 'role': 'videollamb.reasoner', 'instruction': 'Produce the downstream video QA, captioning or planning output from recurrent memory.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'videollamb',
    "version": 'iccv2025',
    "semantic_contract": 'videollamb.memory.v2',
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
        evidence=('videollamb' + ".phase-transcript", 'videollamb' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('videollamb' + "_trajectory",),
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
