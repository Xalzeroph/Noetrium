from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    EvaluationMetricSpec,
    EvaluationReducerKind,
    EvaluationReducerSpec,
    EvaluationScoreView,
    EvaluationScoringProtocol,
    ExperimentModelRoleSpec,
    MeasurementCut,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementValueKind,
    PostHocEvaluationDefinition,
)
from noetrium_platform.research.experimentation.identity import ModelRoleUsage


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


def _scoring_protocol(
    reducer: EvaluationReducerSpec | None = None,
) -> EvaluationScoringProtocol:
    reducer = reducer or EvaluationReducerSpec.builtin(
        "epoch-mean",
        EvaluationReducerKind.MEAN,
    )
    return EvaluationScoringProtocol(
        "score-policy",
        (reducer,),
        (
            EvaluationMetricSpec(
                metric_id="accuracy",
                score_measurement_id="score",
                score_view=EvaluationScoreView.REDUCED,
                operation_id="evaluation.metric.accuracy",
                implementation_digest="a" * 64,
                reducer_id=reducer.reducer_id,
            ),
        ),
        "accuracy",
    )


def _definition(
    role: ExperimentModelRoleSpec,
    *,
    scoring_protocol: EvaluationScoringProtocol | None = None,
) -> PostHocEvaluationDefinition:
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
        scoring_protocol=scoring_protocol or _scoring_protocol(),
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


def test_scoring_policy_changes_evaluation_identity() -> None:
    role = _role(binding_digit="8")
    mean = _definition(role)
    pass_at = _definition(
        role,
        scoring_protocol=_scoring_protocol(
            EvaluationReducerSpec.builtin(
                "pass-at-2",
                EvaluationReducerKind.PASS_AT_K,
                k=2,
            )
        ),
    )

    assert mean.source_execution_digest == pass_at.source_execution_digest
    assert mean.input_cut.cut_digest == pass_at.input_cut.cut_digest
    assert mean.evaluation_digest != pass_at.evaluation_digest


def test_posthoc_evaluation_rejects_execution_only_role() -> None:
    with pytest.raises(ValueError, match="evaluation-capable"):
        _definition(
            replace(_role(binding_digit="8"), usage=ModelRoleUsage.EXECUTION)
        )
