from __future__ import annotations

from .definition import REPRODUCTION

METHOD_PHASES = (
    {'phase_id': 'evaluate_initial', 'role': 'aflow.evaluator', 'instruction': 'Evaluate the initial executable workflow on the paper validation protocol and retain score/cost/log evidence.', 'max_visits': 1},
    {'phase_id': 'select_parent', 'role': 'aflow.search', 'instruction': 'Select a parent from the top-k pool with the paper mixed uniform/softmax sampling rule.', 'max_visits': 1},
    {'phase_id': 'propose', 'role': 'aflow.optimizer', 'instruction': 'Generate an experience-conditioned workflow mutation using the released operators and failure logs.', 'max_visits': 1},
    {'phase_id': 'evaluate_candidate', 'role': 'aflow.evaluator', 'instruction': 'Execute the generated workflow on the validation repetitions and record scores, costs, logs and receipts.', 'max_visits': 1},
    {'phase_id': 'record_generation', 'role': 'aflow.search', 'instruction': 'Update workflow experience, parent-child lineage and the ranked candidate pool.', 'max_visits': 1},
    {'phase_id': 'check_convergence', 'role': 'aflow.search', 'instruction': 'Apply the top-k convergence rule and either continue search or finalize the best workflow.', 'max_visits': 1},
)

METHOD_SPEC = {
    "method_id": 'aflow',
    "version": 'iclr2025',
    "semantic_contract": 'aflow.optimization.v2',
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
        evidence=('aflow' + ".phase-transcript", 'aflow' + ".effect-receipts"),
        metrics=("task_success", "method_phase_count"),
        artifacts=('aflow' + "_trajectory",),
    )
    method.phases(METHOD_PHASES, max_cycles=20)
    return method

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = (
    "METHOD_SPEC", "METHOD_PHASES", "configure_method", "METHOD_CONFIGURER",
    "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS",
)
