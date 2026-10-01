from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'observe', 'role': 'providellm.visual', 'instruction': 'Encode the streaming visual observation through the released DETR/Q-Former path.', 'max_visits': 1},
    {'phase_id': 'short_term', 'role': 'providellm.memory', 'instruction': 'Maintain the bounded short-term visual-token FIFO.', 'max_visits': 1},
    {'phase_id': 'verbalize', 'role': 'providellm.memory', 'instruction': 'Create long-term verbalized tokens at the paper long-term entry point with duplicate suppression.', 'max_visits': 1},
    {'phase_id': 'interleave', 'role': 'providellm.memory', 'instruction': 'Interleave long- and short-term memory according to the multimodal cache policy.', 'max_visits': 1},
    {'phase_id': 'answer', 'role': 'providellm.reasoner', 'instruction': 'Answer the streaming dialogue query from the current interleaved memory.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'providellm',
    "version": 'iccv2025',
    "semantic_contract": 'providellm.memory.v2',
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
        evidence=('providellm' + ".phase-transcript", 'providellm' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('providellm' + "_trajectory",),
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
