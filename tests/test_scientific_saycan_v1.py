import math
from collections.abc import Mapping
from pathlib import Path

import pytest

from noetrium.platform import run_method_program
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)

from research.reproductions.saycan import (
    SAYCAN_FIDELITY,
    SAYCAN_METHOD_PROGRAM,
    SayCanLanguageScoringAgentLoop,
    SayCanLanguageScoringRequest,
    saycan_initial_state,
    select_saycan_skill,
)


def test_saycan_fidelity_pins_paper_scoring_rule() -> None:
    assert SAYCAN_FIDELITY.paper_arxiv == "2204.01691"
    assert SAYCAN_FIDELITY.language_score_transform == "exp"
    assert SAYCAN_FIDELITY.combined_score_rule == "exp(llm_log_score) * affordance_score"
    assert SAYCAN_FIDELITY.selection_rule == "argmax-first-in-option-order"
    assert SAYCAN_FIDELITY.normalization_rule == "clip(combined / max(combined), 0, 1)"
    assert SAYCAN_FIDELITY.termination_string == "done()"
    assert SAYCAN_FIDELITY.termination_affordance == pytest.approx(0.2)
    assert SAYCAN_FIDELITY.demo_max_tasks == 5
    assert SAYCAN_FIDELITY.affordance_scores_frozen_during_planning is True
    assert SAYCAN_FIDELITY.planning_precedes_skill_execution is True
    assert SAYCAN_FIDELITY.skill_execution_is_external is True


def test_saycan_multiplies_language_probability_by_affordance_then_normalizes() -> None:
    selection = select_saycan_skill(
        {
            "pick apple": math.log(0.8),
            "open drawer": math.log(0.5),
        },
        {
            "pick apple": 0.25,
            "open drawer": 0.9,
        },
    )

    assert selection.selected_skill == "open drawer"
    rows = {row.skill: row for row in selection.scores}
    assert rows["pick apple"].combined_score == pytest.approx(0.2)
    assert rows["open drawer"].combined_score == pytest.approx(0.45)
    assert rows["pick apple"].normalized_score == pytest.approx(0.2 / 0.45)
    assert rows["open drawer"].normalized_score == pytest.approx(1.0)


def test_saycan_affordance_can_veto_semantically_likely_skill() -> None:
    selection = select_saycan_skill(
        {"impossible": math.log(0.99), "feasible": math.log(0.2)},
        {"impossible": 0.0, "feasible": 1.0},
    )
    assert selection.selected_skill == "feasible"


def test_saycan_fails_closed_on_score_domain_or_skill_set_drift() -> None:
    with pytest.raises(ValueError, match="same non-empty skill set"):
        select_saycan_skill({"a": -1.0}, {"b": 0.5})
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        select_saycan_skill({"a": -1.0}, {"a": 1.1})
    with pytest.raises(ValueError, match="positive mass"):
        select_saycan_skill({"a": -1.0}, {"a": 0.0})



def test_saycan_ties_preserve_released_option_order() -> None:
    selection = select_saycan_skill(
        {"first": 0.0, "second": 0.0},
        {"first": 0.5, "second": 0.5},
    )
    assert selection.selected_skill == "first"
    assert [row.skill for row in selection.scores] == ["first", "second"]



def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="saycan-run",
        trace_id="trace-saycan",
        span_id="span-saycan",
        study_id="saycan",
        task_id="pick-place",
        decision_cycle_id="cycle-saycan",
    )


class _SayCanScorer:
    def __init__(self, *, always_skill: bool = False) -> None:
        self.always_skill = always_skill
        self.requests: list[SayCanLanguageScoringRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "scorer": "saycan-test",
            "always_skill": self.always_skill,
            "implementation_revision": 1,
        })

    def score(
        self,
        request: SayCanLanguageScoringRequest,
        context: ExecutionContext,
    ) -> Mapping[str, float]:
        assert context.run_id == "saycan-run"
        self.requests.append(request)
        skill = "robot.pick_and_place(red block, red bowl)"
        done = "done()"
        if self.always_skill or request.planning_step == 0:
            return {skill: 0.0, done: -4.0}
        return {skill: -4.0, done: 0.0}


class _SayCanEmbodiedCapability:
    def __init__(self, scorer: _SayCanScorer) -> None:
        self.scorer = scorer
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "environment.act",
            "1",
            "noetrium.environment.action-capability.request.v1",
            "noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "environment.act"
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        assert request.payload["action_type"] == "embodied_skill"
        payload = request.payload["payload"]
        assert isinstance(payload, Mapping)
        assert payload["skill"] == "robot.pick_and_place(red block, red bowl)"
        # Released SayCan demo plans the complete sequence before robot execution.
        expected_planning_calls = 5 if self.scorer.always_skill else 2
        assert len(self.scorer.requests) == expected_planning_calls
        digest = capability_request_digest(request)
        call = len(self.requests)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"saycan-obs-{call}",
                    "generation": f"saycan-env-{call}",
                    "payload": {
                        "executed_skill": payload["skill"],
                        "execution_index": payload["execution_index"],
                    },
                    "artifact_refs": (),
                },
            },
            generation=f"saycan-env-{call}",
            effect=EffectReceipt(
                effect_id=f"saycan-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_saycan_method_program_plans_before_any_skill_execution(
    tmp_path: Path,
) -> None:
    scorer = _SayCanScorer()
    environment = _SayCanEmbodiedCapability(scorer)
    skill = "robot.pick_and_place(red block, red bowl)"
    initial_state = saycan_initial_state(
        planning_prompt="objects = [red block, red bowl]\n# put red in red bowl\n",
        options=(skill, "done()"),
        affordance_scores={skill: 1.0, "done()": 0.2},
    )
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=SayCanLanguageScoringAgentLoop(scorer),
    )

    result = run_method_program(
        SAYCAN_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial_state,
        state_root=tmp_path / "method-machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["planned_steps"] == (skill, "done()")
    assert result.value["executable_steps"] == (skill,)
    assert result.value["planning_calls"] == 2
    assert result.value["terminated_by_done"] is True
    assert result.value["hit_planning_budget"] is False
    assert result.value["executed_skill_count"] == 1
    assert len(scorer.requests) == 2
    assert len(environment.requests) == 1
    assert scorer.requests[1].prompt.endswith(skill + "\n")


def test_saycan_method_program_preserves_five_step_demo_budget(
    tmp_path: Path,
) -> None:
    scorer = _SayCanScorer(always_skill=True)
    environment = _SayCanEmbodiedCapability(scorer)
    skill = "robot.pick_and_place(red block, red bowl)"
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=SayCanLanguageScoringAgentLoop(scorer),
    )

    result = run_method_program(
        SAYCAN_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=saycan_initial_state(
            planning_prompt="objects = [red block, red bowl]\n# loop\n",
            options=(skill, "done()"),
            affordance_scores={skill: 1.0, "done()": 0.2},
        ),
        state_root=tmp_path / "method-machine-budget",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["planning_calls"] == 5
    assert result.value["terminated_by_done"] is False
    assert result.value["hit_planning_budget"] is True
    assert result.value["planned_steps"] == (skill,) * 5
    assert result.value["executed_skill_count"] == 5
    assert len(scorer.requests) == 5
    assert len(environment.requests) == 5
