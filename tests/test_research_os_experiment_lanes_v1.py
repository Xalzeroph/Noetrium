
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product import research_os as api
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    materialize_research_study_spec,
)


def _return(call):
    return {"ok": True}


def _configure_alpha(method):
    method.flow.finish("run", "test.alpha", _return)
    return method


def _configure_beta(method):
    method.flow.finish("run", "test.beta", _return)
    return method


def _study() -> dict[str, object]:
    task = {
        "task_id": "task-a",
        "revision_id": "1",
        "family": "family",
        "schema_id": "task.v1",
        "content": {"goal": "do task"},
    }
    return {
        "project_id": "paper",
        "study_id": "comparison",
        "benchmark": {
            "benchmark_id": "benchmark",
            "revision_id": "1",
            "task_schema_id": "task.v1",
            "tasks": (task,),
            "splits": ({"split_id": "all", "task_ids": ("task-a",)},),
        },
        "benchmark_split_id": "all",
        "method": {
            "role": "agent",
            "kind": "agent_method",
            "implementation": "placeholder",
            "treatment": "full",
            "capabilities": (),
            "configurations": (),
            "depends_on": (),
        },
        "models": {
            "agent_model": {
                "requirement": "model",
                "usage": "execution",
                "required": True,
                "max_bindings": 1,
            }
        },
        "measurements": (
            {
                "measurement_id": "success",
                "schema_id": "measurement.scalar.v1",
                "value_kind": "scalar",
                "semantic_kind": "task_success",
                "scale": "binary",
                "source_path": "success",
                "reducer": "mean",
            },
        ),
        "trial": {
            "protocol_id": "trial",
            "configuration_digest": canonical_digest({"trial": 1}),
        },
        "repetitions": 2,
        "seeds": ("seed-a", "seed-b"),
        "limits": {"budget_id": "budget", "max_steps": 8},
        "assignment_workloads": ({"task_ids": ("task-a",)},),
        "workload_id": "workload",
        "trial_provider_requirement_id": "trial.method-program",
        "replay_level": "observational",
        "environment_session_scope": "task",
        "factors": (),
    }


def test_experiment_lanes_expand_to_canonical_single_method_studies() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method(
        "method.alpha",
        _configure_alpha,
        method_id="alpha",
        entrypoint="run",
    )
    builder.method(
        "method.beta",
        _configure_beta,
        method_id="beta",
        entrypoint="run",
    )
    builder.model("model", config={"required_model": "test"})
    builder.environment("environment", config={"category_id": "text"})
    builder.experiment(
        "e1",
        study=_study(),
        definitions=("model", "environment"),
        lanes={
            "alpha": {
                "method": "method.alpha",
                "treatment": "released",
            },
            "beta": {
                "method": "method.beta",
                "treatment": "full",
            },
        },
        config={"paper_primary": True},
    )
    program = builder.freeze()

    node_by_id = {row.node_id: row for row in program.nodes}
    assert set(node_by_id) == {"e1.alpha", "e1.beta"}
    assert set(node_by_id["e1.alpha"].definition_ids) == {
        "method.alpha",
        "model",
        "environment",
        "e1.alpha.protocol",
    }
    assert node_by_id["e1.alpha"].config["experiment_group"] == "e1"
    assert node_by_id["e1.beta"].config["lane_id"] == "beta"

    definition_by_id = {
        row.definition_id: row for row in program.definitions
    }
    alpha = materialize_research_study_spec(
        definition_by_id["e1.alpha.protocol"].config["study"]
    )
    beta = materialize_research_study_spec(
        definition_by_id["e1.beta.protocol"].config["study"]
    )
    assert alpha.study_id == "e1.alpha.study"
    assert beta.study_id == "e1.beta.study"
    assert alpha.experiment_id == "e1.alpha"
    assert beta.experiment_id == "e1.beta"
    assert alpha.binding_requirements.participants[0].method_id == "alpha"
    assert beta.binding_requirements.participants[0].method_id == "beta"
    assert alpha.binding_requirements.participants[0].treatment_id == "released"
    assert beta.binding_requirements.participants[0].treatment_id == "full"

    # Fairness-critical fields are shared by construction.
    assert alpha.benchmark.cut_digest == beta.benchmark.cut_digest
    assert alpha.seeds == beta.seeds
    assert alpha.assignment_workloads == beta.assignment_workloads
    assert alpha.measurement_protocol.definitions == beta.measurement_protocol.definitions
    assert alpha.execution_policy == beta.execution_policy
    assert alpha.execution_policy.environment_session_scope == "task"


def test_experiment_lanes_reject_non_method_definition() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.model("model", config={"required_model": "test"})
    try:
        builder.experiment(
            "e1",
            study=_study(),
            lanes={
                "bad": {
                    "method": "model",
                    "treatment": "full",
                }
            },
        )
    except ValueError as exc:
        assert "unknown Method definition" in str(exc)
    else:
        raise AssertionError("non-Method experiment lane should fail closed")


def test_experiment_lanes_reject_lane_benchmark_override() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method(
        "method.alpha",
        _configure_alpha,
        method_id="alpha",
        entrypoint="run",
    )
    try:
        builder.experiment(
            "e1",
            study=_study(),
            lanes={
                "alpha": {
                    "method": "method.alpha",
                    "treatment": "full",
                    "benchmark": {"benchmark_id": "different"},
                }
            },
        )
    except ValueError as exc:
        assert "unsupported keys" in str(exc)
    else:
        raise AssertionError("fairness-critical lane override should fail closed")
