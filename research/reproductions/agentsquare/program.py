from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'evolve', 'role': 'agentsquare.evolution', 'instruction': 'Evolve planning, reasoning, tool-use and memory modules from the current archive.', 'max_visits': 1},
    {'phase_id': 'validate_modules', 'role': 'agentsquare.validation', 'instruction': 'Validate each evolved module under its module-specific constraints.', 'max_visits': 1},
    {'phase_id': 'evaluate_evolution', 'role': 'agentsquare.evaluation', 'instruction': 'Evaluate evolved candidate agents on the paper benchmark episodes.', 'max_visits': 1},
    {'phase_id': 'recombine', 'role': 'agentsquare.recombination', 'instruction': 'Recombine validated modules into candidate agents.', 'max_visits': 1},
    {'phase_id': 'predict', 'role': 'agentsquare.predictor', 'instruction': 'Predict candidate performance with the paper train split and capped history.', 'max_visits': 1},
    {'phase_id': 'evaluate_recombined', 'role': 'agentsquare.evaluation', 'instruction': 'Evaluate selected recombined agents with the released episode budget.', 'max_visits': 1},
    {'phase_id': 'record_iteration', 'role': 'agentsquare.search', 'instruction': 'Update module archives and search history from measured performance.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'agentsquare',
    "version": 'paper-protocol',
    "semantic_contract": 'agentsquare.optimization.v2',
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
        evidence=('agentsquare' + ".phase-transcript", 'agentsquare' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('agentsquare' + "_trajectory",),
    )
    method.phases(METHOD_PHASES, max_cycles=10)
    return method

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = (
    "METHOD_SPEC", "METHOD_PHASES", "configure_method", "METHOD_CONFIGURER",
    "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS",
)
