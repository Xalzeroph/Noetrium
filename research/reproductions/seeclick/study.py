from __future__ import annotations
from research.reproductions import _support as _rs
from research.benchmarks.screenspot import SCREENSPOT_BENCHMARK_ID

from .fidelity import SEECLICK_FIDELITY
from .program import SEECLICK_METHOD_PROGRAM

SEECLICK_SCREENSPOT_TRIAL_PROTOCOL = _rs.study_protocol(
    "seeclick.acl2024.screenspot.v1",
    _rs.canonical_digest({
        "program_digest": SEECLICK_METHOD_PROGRAM.program_digest,
        "base_model": SEECLICK_FIDELITY.base_model,
        "coordinate_range": (
            SEECLICK_FIDELITY.coordinate_min,
            SEECLICK_FIDELITY.coordinate_max,
        ),
        "coordinate_precision_decimals": (
            SEECLICK_FIDELITY.coordinate_precision_decimals
        ),
        "grounding_task": "text_2_point",
    }),
)


@_rs.study_factory('benchmark')
def build_seeclick_screenspot_study(
    benchmark,
    *,
    split_id: str,
):
    if benchmark.benchmark_id != SCREENSPOT_BENCHMARK_ID:
        raise ValueError("SeeClick study requires ScreenSpot")
    if not benchmark.selected_tasks(split_id):
        raise ValueError("SeeClick ScreenSpot study requires a non-empty split")
    return _rs.study_spec(project_id="seeclick-acl2024-reproduction",
        study_id=f"seeclick-screenspot-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=_rs.study_participant(
            role="seeclick",
            kind="visual_gui_grounder",
            implementation="seeclick-paper-era",
            treatment="gui-grounding-pretrained",
            configurations=("seeclick.text-to-point",),
        ),
        models={
            "seeclick": _rs.study_model(
                "model.seeclick-qwen-vl-chat",
                prompt="seeclick.screenspot.paper-era",
            ),
        },
        measurements=(
            _rs.scalar_measurement(
                "grounding_accuracy",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="gui_grounding_accuracy",
                scale="ratio",
                domain="screenspot",
            ),
            _rs.scalar_measurement(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="screenspot",
            ),
        ),
        trial=SEECLICK_SCREENSPOT_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("0",),
        limits=_rs.trial_budget(
            "seeclick-screenspot",
            max_steps=4,
            max_model_calls=1,
            max_working_seconds=300.0,
        ),
        replay_level='observational',
    )


__all__ = [
    "SEECLICK_SCREENSPOT_TRIAL_PROTOCOL",
    "build_seeclick_screenspot_study",
]
