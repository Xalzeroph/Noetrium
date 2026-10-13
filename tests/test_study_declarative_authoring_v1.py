from __future__ import annotations

import copy

import pytest

from noetrium_platform.capabilities.participant.api import (
    participant_requirement_capabilities,
    participant_requirement_method_id,
    participant_requirement_role,
    participant_waves,
)
from noetrium_platform.research.experimentation.binding import (
    binding_requirements_model_role,
    binding_requirements_participants,
    binding_requirements_topology,
    model_role_requirement_id,
    model_role_requirement_prompt,
    model_role_requirement_usage,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage, ReplayLevel
from noetrium_platform.research.experimentation.lifecycle.study.api.authoring import (
    materialize_research_study_spec,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    execution_policy_budget,
    execution_policy_replay_level,
    factor_level_id,
    factor_levels,
    measurement_definitions,
    measurement_id,
    study_benchmark_split_id,
    study_binding_requirements,
    study_definition_digest,
    study_execution_policy,
    study_factors,
    study_id,
    study_measurement_protocol,
    study_project_id,
    study_repetitions,
    study_seeds,
    trial_budget_id,
)


def _mapping() -> dict[str, object]:
    return {
        "project_id": "react-reproduction",
        "study_id": "react-alfworld",
        "benchmark": {
            "benchmark_id": "benchmark",
            "revision_id": "1",
            "task_schema_id": "task.v1",
            "tasks": (
                {
                    "task_id": "task-a",
                    "family": "family-a",
                    "content": {"objective": "solve a"},
                },
                {
                    "task_id": "task-b",
                    "family": "family-b",
                    "content": {"objective": "solve b"},
                },
            ),
            "splits": (
                {"split_id": "eval", "task_ids": ("task-b", "task-a")},
            ),
        },
        "benchmark_split_id": "eval",
        "method": {
            "role": "agent",
            "kind": "agent",
            "implementation": "react",
            "treatment": "released-code",
            "capabilities": ("environment.act",),
            "configurations": ("react.prompt",),
        },
        "participants": (),
        "models": {
            "action": {
                "requirement": "model.react.action",
                "prompt": "react.prompt",
            }
        },
        "measurements": (
            {
                "measurement_id": "success",
                "schema_id": "measurement.boolean.v1",
                "value_kind": "scalar",
                "semantic_kind": "task_success",
                "scale": "binary",
            },
        ),
        "trial": {
            "protocol_id": "trial.react",
            "configuration_digest": "3" * 64,
        },
        "repetitions": 3,
        "seeds": ("seed-1", "seed-2", "seed-3"),
        "limits": {
            "budget_id": "react-limits",
            "max_turns": 49,
            "max_tokens": 100_000,
        },
        "replay_level": ReplayLevel.OBSERVATIONAL.value,
    }


def test_mapping_lowers_directly_to_one_study_unit() -> None:
    study = materialize_research_study_spec(_mapping())

    assert study_project_id(study) == "react-reproduction"
    assert study_id(study) == "react-alfworld"
    assert study_repetitions(study) == 3
    assert study_seeds(study) == ("seed-1", "seed-2", "seed-3")
    assert study_benchmark_split_id(study) == "eval"

    policy = study_execution_policy(study)
    budget = execution_policy_budget(policy)
    assert budget is not None
    assert trial_budget_id(budget) == "react-limits"
    assert budget.parameters["max_turns"] == 49
    assert execution_policy_replay_level(policy) is ReplayLevel.OBSERVATIONAL

    requirements = study_binding_requirements(study)
    participant = binding_requirements_participants(requirements)[0]
    assert participant_requirement_role(participant) == "agent"
    assert participant_requirement_method_id(participant) == "react"
    assert participant_requirement_capabilities(participant) == ("environment.act",)

    action = binding_requirements_model_role(requirements, "action")
    assert model_role_requirement_id(action) == "model.react.action"
    assert model_role_requirement_prompt(action) == "react.prompt"
    assert model_role_requirement_usage(action) is ModelRoleUsage.EXECUTION

    measurements = measurement_definitions(study_measurement_protocol(study))
    assert tuple(measurement_id(row) for row in measurements) == ("success",)
    assert measurements[0].parameters["semantic_kind"] == "task_success"


def test_multi_participant_and_evaluation_model_are_native_unit_members() -> None:
    spec = _mapping()
    spec["participants"] = (
        {
            "role": "user",
            "kind": "user_simulator",
            "implementation": "tau-user-simulator",
            "treatment": "default-user",
        },
    )
    spec["models"] = {
        "action": "model.tau.agent",
        "user": "model.tau.user",
        "grader": {
            "requirement": "model.tau.grader",
            "usage": ModelRoleUsage.EVALUATION.value,
        },
    }
    study = materialize_research_study_spec(spec)
    requirements = study_binding_requirements(study)
    participants = binding_requirements_participants(requirements)
    assert tuple(participant_requirement_role(row) for row in participants) == (
        "agent",
        "user",
    )
    assert model_role_requirement_id(
        binding_requirements_model_role(requirements, "user")
    ) == "model.tau.user"
    assert model_role_requirement_usage(
        binding_requirements_model_role(requirements, "grader")
    ) is ModelRoleUsage.EVALUATION


def test_participant_topology_accepts_hyperrelations_and_cycles_without_new_carrier() -> None:
    spec = _mapping()
    spec["participants"] = (
        {
            "role": "critic",
            "kind": "agent",
            "implementation": "critic",
            "treatment": "critic",
        },
        {
            "role": "judge",
            "kind": "agent",
            "implementation": "judge",
            "treatment": "judge",
        },
    )
    spec["participant_topology"] = {
        "edges": (
            {
                "sources": ("agent", "critic"),
                "targets": ("judge",),
                "relation": "participant.communication",
                "parameters": {"channel": "debate"},
            },
            {
                "source_role": "agent",
                "target_role": "critic",
                "relation": "participant.depends-on",
            },
            {
                "source_role": "critic",
                "target_role": "agent",
                "relation": "participant.depends-on",
            },
        )
    }
    study = materialize_research_study_spec(spec)
    topology = binding_requirements_topology(study_binding_requirements(study))
    assert participant_waves(topology) == (("agent", "critic", "judge"),)


def test_author_declaration_order_is_canonical() -> None:
    left = _mapping()
    left["factors"] = (
        {
            "factor_id": "factor-z",
            "levels": (
                {"level_id": "z-control", "value": "z0", "control": True},
                {"level_id": "z1", "value": "z1"},
            ),
        },
        {
            "factor_id": "factor-a",
            "levels": (
                {"level_id": "a-control", "value": "a0", "control": True},
                {"level_id": "a1", "value": "a1"},
            ),
        },
    )
    left["measurements"] = (
        {
            "measurement_id": "z-metric",
            "schema_id": "metric.z.v1",
            "value_kind": "scalar",
        },
        {
            "measurement_id": "a-metric",
            "schema_id": "metric.a.v1",
            "value_kind": "scalar",
        },
    )
    right = copy.deepcopy(left)
    right["factors"] = tuple(reversed(right["factors"]))
    right["measurements"] = tuple(reversed(right["measurements"]))

    a = materialize_research_study_spec(left)
    b = materialize_research_study_spec(right)
    assert study_definition_digest(a) == study_definition_digest(b)
    assert tuple(row.unit_id for row in study_factors(a)) == ("factor-a", "factor-z")
    assert tuple(
        measurement_id(row)
        for row in measurement_definitions(study_measurement_protocol(a))
    ) == ("a-metric", "z-metric")
    assert tuple(factor_level_id(row) for row in factor_levels(study_factors(a)[0])) == (
        "a-control",
        "a1",
    )


def test_authoring_fails_closed_on_missing_scientific_content() -> None:
    spec = _mapping()
    spec["seeds"] = ()
    with pytest.raises((TypeError, ValueError), match="seeds"):
        materialize_research_study_spec(spec)

    spec = _mapping()
    spec["benchmark"] = {
        "benchmark_id": "benchmark",
        "revision_id": "1",
        "task_schema_id": "task.v1",
        "tasks": ({"task_id": "t", "family": "f"},),
    }
    with pytest.raises(ValueError, match="inline content"):
        materialize_research_study_spec(spec)


def test_zero_glue_authoring_is_deterministic() -> None:
    first = materialize_research_study_spec(_mapping())
    second = materialize_research_study_spec(copy.deepcopy(_mapping()))
    assert first == second
    assert first.unit_digest == second.unit_digest
    assert len(first.unit_digest) == 64


def test_study_authoring_accepts_frozen_native_benchmark_unit_without_reencoding() -> None:
    from noetrium_platform.research.experimentation.lifecycle.study.api import (
        benchmark_cut_unit,
        split_unit,
        task_unit,
        study_benchmark,
    )
    task = task_unit(
        "native-task",
        revision_id="native-r1",
        family="native",
        schema_id="native.task.v1",
        content_digest=None,
        content={"objective": "solve native"},
    )
    benchmark = benchmark_cut_unit(
        "native-benchmark",
        "native-r1",
        "a" * 64,
        "native.task.v1",
        (task,),
        splits=(split_unit("eval", ("native-task",)),),
    )
    spec = _mapping()
    spec["benchmark"] = benchmark
    spec["benchmark_split_id"] = "eval"
    study = materialize_research_study_spec(spec)
    embedded = study_benchmark(study)
    assert embedded is benchmark
    assert embedded.unit_digest == benchmark.unit_digest
