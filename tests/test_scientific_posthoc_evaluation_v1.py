from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentModelRoleSpec,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage
from noetrium_platform.research.experimentation.study.api import (
    MeasurementCut,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    PostHocEvaluationDefinition,
)


def _role(
    *,
    binding_digit: str,
    usage: ModelRoleUsage = ModelRoleUsage.EVALUATION,
) -> ExperimentModelRoleSpec:
    return ExperimentModelRoleSpec(
        role="grader",
        requirement_id="model.grader",
        provider_id="model.provider",
        deployment_id="grader-deployment",
        deployment_generation="1" * 64,
        model_identity_digest="2" * 64,
        model_stack_digest="3" * 64,
        binding_digest=binding_digit * 64,
        usage=usage,
    )


def _definition(role: ExperimentModelRoleSpec) -> PostHocEvaluationDefinition:
    return PostHocEvaluationDefinition(
        evaluation_id="score-pass-1",
        evaluator_id="benchmark.scorer",
        evaluator_version="1",
        implementation_digest="4" * 64,
        configuration_digest="5" * 64,
        source_execution_digest="6" * 64,
        input_cut=MeasurementCut(record_digests=("7" * 64,)),
        output_protocol=MeasurementProtocol(
            "score-output",
            (
                MeasurementDefinition(
                    "score",
                    "measurement.scalar.v1",
                    MeasurementValueKind.SCALAR,
                    semantic_kind="task_reward",
                ),
            ),
        ),
        model_roles=(role,),
    )


def test_rebinding_grader_creates_new_evaluation_without_changing_execution_cut() -> None:
    first = _definition(_role(binding_digit="8"))
    rescored = first.rebind_model_roles((_role(binding_digit="9"),))

    assert first.source_execution_digest == rescored.source_execution_digest
    assert first.input_cut.cut_digest == rescored.input_cut.cut_digest
    assert first.evaluation_digest != rescored.evaluation_digest
    assert (
        first.evaluation_model_roles_digest
        != rescored.evaluation_model_roles_digest
    )


def test_posthoc_evaluation_rejects_execution_only_role() -> None:
    with pytest.raises(ValueError, match="evaluation-capable"):
        _definition(
            replace(_role(binding_digit="8"), usage=ModelRoleUsage.EXECUTION)
        )
