from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_REVISION,
    ALFWORLD_PAPER_EVAL_SPLIT,
)

from .fidelity import REFLEXION_ALFWORLD_FIDELITY

REFLEXION_ALFWORLD_TRIAL_PROTOCOL = _rs.study_protocol(
    "reflexion.alfworld.paper-era.v1",
    _rs.canonical_digest(
        {
            "max_trials": REFLEXION_ALFWORLD_FIDELITY.max_trials,
            "max_turns_per_trial": REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial,
            "action_model": REFLEXION_ALFWORLD_FIDELITY.reference_action_model,
            "reflection_model": REFLEXION_ALFWORLD_FIDELITY.reference_reflection_model,
            "reflection_memory_window": REFLEXION_ALFWORLD_FIDELITY.reflection_memory_window,
            "reflection_after_failed_trial_only": REFLEXION_ALFWORLD_FIDELITY.reflection_after_failed_trial_only,
        }
    ),
)


@_rs.requires_benchmark_cut(
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_REVISION,
    split_ids=(ALFWORLD_PAPER_EVAL_SPLIT,),
)
@_rs.study_factory('benchmark')
def build_reflexion_alfworld_study(benchmark):
    """Freeze one per-task Reflexion campaign; the ten learning trials stay method-owned."""

    if benchmark.benchmark_id != ALFWORLD_BENCHMARK_ID:
        raise ValueError("Reflexion ALFWorld study requires the shared ALFWorld benchmark cut")
    benchmark.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)
    return _rs.study_spec(project_id="reflexion-alfworld-reproduction",
        study_id="reflexion-alfworld-paper-era",
        benchmark=benchmark,
        benchmark_split_id=ALFWORLD_PAPER_EVAL_SPLIT,
        method=_rs.study_participant(
            role="agent",
            kind="agent",
            implementation="reflexion",
            treatment="verbal-reflection",
            capabilities=("environment.act", "environment.reset"),
            configurations=(
                "reflexion.alfworld.prompt",
                "reflexion.alfworld.reflection-prompt",
                "reflexion.alfworld.model-roles",
            ),
        ),
        models={
            "action": _rs.study_model(
                "model.reflexion.action",
                prompt="reflexion.alfworld.prompt",
            ),
            "reflection": _rs.study_model(
                "model.reflexion.reflection",
                prompt="reflexion.alfworld.reflection-prompt",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="alfworld",
            ),
            _rs.scalar_measurement(
                "first_success_trial",
                schema_id="noetrium.measurement.count.v1",
                unit="trial",
                semantic_kind="learning_curve",
                scale="count",
                domain="alfworld",
            ),
            _rs.scalar_measurement(
                "trials_used",
                schema_id="noetrium.measurement.count.v1",
                unit="trial",
                semantic_kind="resource_usage",
                scale="count",
                domain="alfworld",
            ),
        ),
        trial=REFLEXION_ALFWORLD_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("42",),
        limits=_rs.trial_budget(
            "reflexion-alfworld-10x49-turn",
            max_steps=8192,
            max_turns=(
                REFLEXION_ALFWORLD_FIDELITY.max_trials
                * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
            ),
            max_model_calls=(
                REFLEXION_ALFWORLD_FIDELITY.max_trials
                * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
                * REFLEXION_ALFWORLD_FIDELITY.action_candidate_attempts
                + REFLEXION_ALFWORLD_FIDELITY.max_trials
            ),
        ),
        replay_level='observational',
    )



__all__ = ["REFLEXION_ALFWORLD_TRIAL_PROTOCOL", "build_reflexion_alfworld_study"]
