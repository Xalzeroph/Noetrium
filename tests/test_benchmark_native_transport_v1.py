from __future__ import annotations

import pytest

from noetrium_platform.research.experimentation.lifecycle.study.api import (
    benchmark_authoring_mapping,
    benchmark_cut_digest,
    benchmark_selected_tasks,
    benchmark_split_projection_unit,
    materialize_research_study_spec,
    study_benchmark,
)
from research.benchmarks.mineevolve_long_horizon_70 import build_native_cut


def _study_spec(benchmark, split_id: str):
    return {
        "project_id": "fixture",
        "study_id": "native-transport",
        "benchmark": benchmark_authoring_mapping(benchmark),
        "benchmark_split_id": split_id,
        "method": {
            "role": "agent",
            "kind": "method",
            "implementation": "method.fixture",
            "treatment": "full",
            "capabilities": (),
            "configurations": (),
            "depends_on": (),
        },
        "models": {},
        "measurements": ({
            "measurement_id": "success",
            "schema_id": "fixture.success.v1",
            "value_kind": "scalar",
            "semantic_kind": "task_success",
        },),
        "trial": {"protocol_id": "fixture", "configuration_digest": "a" * 64},
        "repetitions": 1,
        "seeds": ("seed",),
        "assignment_workloads": tuple(
            {"task_ids": (task.parameters["task_id"],), "task_graph": {"edges": ()}}
            for task in benchmark_selected_tasks(benchmark)
        ),
        "assignment_relations": (),
        "experiment_id": "fixture",
        "workload_id": "fixture",
        "trial_provider_requirement_id": "trial.fixture",
        "replay_level": "observational",
        "factors": (),
    }


def test_native_split_projection_round_trips_through_json_authoring_boundary():
    projected = benchmark_split_projection_unit(build_native_cut(), "ablation-balanced-28")
    assert len(benchmark_selected_tasks(projected, "ablation-balanced-28")) == 28
    study = materialize_research_study_spec(_study_spec(projected, "ablation-balanced-28"))
    assert benchmark_cut_digest(study_benchmark(study)) == benchmark_cut_digest(projected)


def test_native_projection_transports_only_selected_tasks():
    projected = benchmark_split_projection_unit(build_native_cut(), "ablation-balanced-28")
    transport = benchmark_authoring_mapping(projected)
    assert len(transport["tasks"]) == 28
    assert transport["cut_digest"] == benchmark_cut_digest(projected)


def test_authoring_transport_tamper_fails_closed_on_cut_digest():
    projected = benchmark_split_projection_unit(build_native_cut(), "all")
    transport = dict(benchmark_authoring_mapping(projected))
    transport["cut_digest"] = "f" * 64
    spec = _study_spec(projected, "all")
    spec["benchmark"] = transport
    with pytest.raises(ValueError, match="round-trip exact cut identity"):
        materialize_research_study_spec(spec)
