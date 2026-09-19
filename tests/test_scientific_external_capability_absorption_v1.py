from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.binding import (
    ResearchBindingRequirements,
    ResearchModelRoleRequirement,
)
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentModelRoleSpec,
    ExperimentSpec,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage
from noetrium_platform.research.experimentation.study.api import (
    TaskArtifactSpec,
    TaskDefinition,
    TaskPackageSpec,
    TaskVerifierIsolation,
    TrialBudget,
)


def _resolved_role(
    role: str,
    *,
    usage: ModelRoleUsage,
    member_index: int = 0,
    binding_digit: str = "1",
) -> ExperimentModelRoleSpec:
    return ExperimentModelRoleSpec(
        role=role,
        requirement_id=f"model.{role}",
        provider_id="model.provider",
        deployment_id=f"deployment-{role}-{member_index}",
        deployment_generation="2" * 64,
        model_identity_digest="3" * 64,
        model_stack_digest="4" * 64,
        binding_digest=binding_digit * 64,
        usage=usage,
        member_index=member_index,
    )


def test_named_model_role_requirements_absorb_required_usage_and_panel_semantics() -> None:
    policy = ResearchModelRoleRequirement(
        "policy", "model.shared", usage=ModelRoleUsage.EXECUTION
    )
    grader = ResearchModelRoleRequirement(
        "grader",
        "model.shared",
        usage=ModelRoleUsage.EVALUATION,
        required=False,
        max_bindings=3,
    )
    requirements = ResearchBindingRequirements(
        "trial-provider", model_roles=(policy, grader)
    )
    assert tuple(row.role for row in requirements.model_roles) == ("grader", "policy")
    assert requirements.model_role("grader").required is False
    assert requirements.model_role("grader").max_bindings == 3
    assert policy.requirement_id == grader.requirement_id
    assert policy.requirement_digest != grader.requirement_digest


def test_execution_and_evaluation_model_role_identities_are_separable() -> None:
    policy = _resolved_role("policy", usage=ModelRoleUsage.EXECUTION)
    grader = _resolved_role("grader", usage=ModelRoleUsage.EVALUATION, binding_digit="5")
    experiment = ExperimentSpec(
        "experiment", "study", "project", (), (grader, policy),
        "6" * 64, "7" * 64, 1, "trial.agent", "8" * 64,
    )
    rescored = replace(
        experiment,
        model_roles=(replace(grader, binding_digest="9" * 64), policy),
    )
    assert experiment.model_roles_digest != rescored.model_roles_digest
    assert (
        experiment.evaluation_model_roles_digest
        != rescored.evaluation_model_roles_digest
    )
    assert (
        experiment.execution_model_roles_digest
        == rescored.execution_model_roles_digest
    )


def test_model_role_panel_members_have_stable_member_identity() -> None:
    left = _resolved_role(
        "grader", usage=ModelRoleUsage.EVALUATION, member_index=0, binding_digit="a"
    )
    right = _resolved_role(
        "grader", usage=ModelRoleUsage.EVALUATION, member_index=1, binding_digit="b"
    )
    experiment = ExperimentSpec(
        "experiment", "study", "project", (), (right, left),
        "6" * 64, "7" * 64, 1, "trial.agent", "8" * 64,
    )
    assert tuple((row.role, row.member_index) for row in experiment.model_roles) == (
        ("grader", 0),
        ("grader", 1),
    )


def test_task_package_freezes_verifier_isolation_and_artifact_allowlist() -> None:
    package = TaskPackageSpec(
        package_schema_id="benchmark.task-package.v1",
        instruction_digest="1" * 64,
        environment_requirement_id="environment.browser",
        verifier_requirement_id="verifier.task",
        verifier_isolation=TaskVerifierIsolation.SEPARATE,
        verifier_environment_requirement_id="environment.verifier",
        artifacts=(
            TaskArtifactSpec("answer", "artifacts/answer.json"),
            TaskArtifactSpec("trace", "artifacts/trace.jsonl", required=False),
        ),
        resource_requirement_digest="2" * 64,
        network_policy_digest="3" * 64,
    )
    task = TaskDefinition(
        "task-1", "rev-1", "browser", "task.v1", "4" * 64, package=package
    )
    changed = replace(
        task,
        package=replace(package, verifier_isolation=TaskVerifierIsolation.SHARED),
    )
    assert task.task_digest != changed.task_digest
    assert task.package is not None
    assert tuple(row.artifact_id for row in task.package.artifacts) == (
        "answer",
        "trace",
    )

    with pytest.raises(ValueError, match="package-relative"):
        TaskArtifactSpec("bad", "../secret")


def test_trial_budget_absorbs_task_level_limits_without_collapsing_step_semantics() -> None:
    budget = TrialBudget(
        "full-limits",
        max_steps=49,
        max_seconds=900,
        max_tokens=100_000,
        max_turns=49,
        max_messages=200,
        max_model_calls=80,
        max_working_seconds=600,
        max_cost_usd=25.0,
    )
    assert budget.max_steps == budget.max_turns == 49
    assert budget.budget_digest == canonical_digest(
        {
            "budget_id": "full-limits",
            "max_steps": 49,
            "max_seconds": 900,
            "max_tokens": 100_000,
            "resource_budget_digest": None,
            "max_turns": 49,
            "max_messages": 200,
            "max_model_calls": 80,
            "max_working_seconds": 600,
            "max_cost_usd": 25.0,
        }
    )
