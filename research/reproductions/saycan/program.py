from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import SAYCAN_FIDELITY, SAYCAN_PAPER_CODE_COMMIT
from .policy import SayCanSelection, select_saycan_skill


_LANGUAGE_AGENT_ID = "saycan.language-scorer"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_ENVIRONMENT_ACTION_TYPE = "embodied_skill"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(f"{field_name} must be a sequence")
    result = tuple(_text(item, field_name) for item in value)
    if not result:
        raise ValueError(f"{field_name} must be non-empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must contain unique values")
    return result


def _score_mapping(
    value: object,
    *,
    options: tuple[str, ...],
    field_name: str,
    bounded: bool,
) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    if set(value) != set(options):
        raise ValueError(f"{field_name} must cover the exact option set")
    result: dict[str, float] = {}
    for option in options:
        score = value[option]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError(f"{field_name} values must be finite numbers")
        numeric = float(score)
        if bounded and not 0.0 <= numeric <= 1.0:
            raise ValueError(f"{field_name} values must be in [0, 1]")
        result[option] = numeric
    return result


@dataclass(frozen=True, slots=True)
class SayCanLanguageScoringRequest:
    prompt: str
    options: tuple[str, ...]
    planning_step: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prompt",
            _text(self.prompt, "SayCan language-scoring prompt"),
        )
        object.__setattr__(
            self,
            "options",
            _string_tuple(self.options, "SayCan options"),
        )
        if type(self.planning_step) is not int or self.planning_step < 0:
            raise ValueError("SayCan planning_step must be non-negative")


@runtime_checkable
class SayCanLanguageScorerPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def score(
        self,
        request: SayCanLanguageScoringRequest,
        context: ExecutionContext,
    ) -> Mapping[str, float]: ...


class SayCanLanguageScoringAgentLoop:
    """Adapter from Method agent execution to paper-owned option scoring."""

    def __init__(self, scorer: SayCanLanguageScorerPort) -> None:
        if not isinstance(scorer, SayCanLanguageScorerPort):
            raise TypeError(
                "SayCan language loop requires SayCanLanguageScorerPort"
            )
        require_sha256(
            scorer.identity_digest,
            "SayCan language scorer identity_digest",
        )
        self._scorer = scorer

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "agent": _LANGUAGE_AGENT_ID,
            "source_commit": SAYCAN_PAPER_CODE_COMMIT,
            "scorer_identity_digest": self._scorer.identity_digest,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != _LANGUAGE_AGENT_ID:
            raise ValueError(
                f"unexpected SayCan agent id: {request.agent_id}"
            )
        options = _string_tuple(
            request.view.get("options", ()),
            "SayCan language-agent options",
        )
        planning_step = request.view.get("planning_step")
        if type(planning_step) is not int or planning_step < 0:
            raise ValueError("SayCan planning_step view is invalid")
        scores = self._scorer.score(
            SayCanLanguageScoringRequest(
                prompt=_text(
                    request.view.get("prompt"),
                    "SayCan language-agent prompt",
                ),
                options=options,
                planning_step=planning_step,
            ),
            request.context,
        )
        ordered = _score_mapping(
            scores,
            options=options,
            field_name="SayCan LLM log-scores",
            bounded=False,
        )
        return MethodAgentResult(
            value=ordered,
            state_update={"llm_log_scores": ordered},
        )


def saycan_initial_state(
    *,
    planning_prompt: str,
    options: tuple[str, ...],
    affordance_scores: Mapping[str, float],
) -> JsonObject:
    prompt = _text(planning_prompt, "SayCan planning_prompt")
    option_tuple = _string_tuple(options, "SayCan options")
    if SAYCAN_FIDELITY.termination_string not in option_tuple:
        raise ValueError("SayCan options must include done()")
    affordances = _score_mapping(
        affordance_scores,
        options=option_tuple,
        field_name="SayCan affordance scores",
        bounded=True,
    )
    termination = SAYCAN_FIDELITY.termination_string
    if not math.isclose(
        affordances[termination],
        SAYCAN_FIDELITY.termination_affordance,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "SayCan done() affordance must match released notebook"
        )
    return {
        "source_commit": SAYCAN_PAPER_CODE_COMMIT,
        "planning_prompt": prompt,
        "options": option_tuple,
        "affordance_scores": affordances,
        "llm_log_scores": {},
        "planned_steps": (),
        "planning_score_tables": (),
        "planning_calls": 0,
        "planning_complete": False,
        "terminated_by_done": False,
        "execution_index": 0,
        "pending_skill": "",
        "execution_results": (),
    }


def _language_view(request: MethodNodeRequest) -> JsonObject:
    options = _string_tuple(
        request.state.get("options", ()),
        "SayCan options",
    )
    calls = request.state.get("planning_calls")
    if type(calls) is not int or calls < 0:
        raise ValueError("SayCan planning_calls state is invalid")
    return {
        "prompt": _text(
            request.state.get("planning_prompt"),
            "SayCan planning prompt",
        ),
        "options": options,
        "planning_step": calls,
    }


def _select_plan_step(request: MethodNodeRequest) -> MethodNodeResult:
    options = _string_tuple(
        request.state.get("options", ()),
        "SayCan options",
    )
    llm_scores = _score_mapping(
        request.state.get("llm_log_scores", {}),
        options=options,
        field_name="SayCan LLM log-scores",
        bounded=False,
    )
    affordances = _score_mapping(
        request.state.get("affordance_scores", {}),
        options=options,
        field_name="SayCan affordance scores",
        bounded=True,
    )
    selection: SayCanSelection = select_saycan_skill(
        llm_scores,
        affordances,
    )
    planned_raw = request.state.get("planned_steps", ())
    if isinstance(planned_raw, (str, bytes, bytearray)) or not isinstance(
        planned_raw,
        Sequence,
    ):
        raise TypeError("SayCan planned_steps must be a sequence")
    planned = [
        _text(step, "SayCan planned step")
        for step in planned_raw
    ]
    planned.append(selection.selected_skill)

    score_tables_raw = request.state.get("planning_score_tables", ())
    if not isinstance(score_tables_raw, (tuple, list)):
        raise TypeError("SayCan planning_score_tables must be a sequence")
    score_tables = list(score_tables_raw)
    score_tables.append({
        "selected_skill": selection.selected_skill,
        "scores": tuple({
            "skill": row.skill,
            "llm_log_score": row.llm_log_score,
            "affordance_score": row.affordance_score,
            "combined_score": row.combined_score,
            "normalized_score": row.normalized_score,
        } for row in selection.scores),
    })

    calls = request.state.get("planning_calls")
    if type(calls) is not int or calls < 0:
        raise ValueError("SayCan planning_calls state is invalid")
    calls += 1
    terminated = selection.selected_skill == SAYCAN_FIDELITY.termination_string
    exhausted = calls >= SAYCAN_FIDELITY.demo_max_tasks
    complete = terminated or exhausted
    prompt = _text(
        request.state.get("planning_prompt"),
        "SayCan planning_prompt",
    ) + selection.selected_skill + "\n"

    return MethodNodeResult(
        value={
            "selected_skill": selection.selected_skill,
            "planning_call": calls,
            "terminated_by_done": terminated,
            "budget_exhausted": exhausted and not terminated,
        },
        state_update={
            "planned_steps": tuple(planned),
            "planning_score_tables": tuple(score_tables),
            "planning_calls": calls,
            "planning_prompt": prompt,
            "planning_complete": complete,
            "terminated_by_done": terminated,
        },
        next_node="execution_route" if complete else "language_score",
    )


def _executable_steps(state: Mapping[str, JsonValue]) -> tuple[str, ...]:
    raw = state.get("planned_steps", ())
    if not isinstance(raw, (tuple, list)):
        raise TypeError("SayCan planned_steps must be a sequence")
    result: list[str] = []
    for step in raw:
        text = _text(step, "SayCan planned step")
        if text == SAYCAN_FIDELITY.termination_string:
            break
        result.append(text)
    return tuple(result)


def _route_execution(request: MethodNodeRequest) -> MethodNodeResult:
    if request.state.get("planning_complete") is not True:
        raise RuntimeError(
            "SayCan execution cannot begin before planning completes"
        )
    steps = _executable_steps(request.state)
    index = request.state.get("execution_index")
    if type(index) is not int or index < 0:
        raise ValueError("SayCan execution_index state is invalid")
    return MethodNodeResult(
        value={
            "execution_index": index,
            "execution_count": len(steps),
            "complete": index >= len(steps),
        },
        next_node="return" if index >= len(steps) else "prepare_skill",
    )


def _prepare_skill(request: MethodNodeRequest) -> MethodNodeResult:
    steps = _executable_steps(request.state)
    index = request.state.get("execution_index")
    if type(index) is not int or not 0 <= index < len(steps):
        raise ValueError("SayCan execution_index is outside planned skills")
    skill = steps[index]
    envelope = environment_action_capability_payload(
        _ENVIRONMENT_ACTION_TYPE,
        {
            "skill": skill,
            "execution_index": index,
            "planned_steps": tuple(steps),
        },
    )
    return MethodNodeResult(
        value=envelope,
        state_update={
            **envelope,
            "pending_skill": skill,
        },
    )


def _record_skill(request: MethodNodeRequest) -> MethodNodeResult:
    skill = _text(
        request.state.get("pending_skill"),
        "SayCan pending_skill",
    )
    index = request.state.get("execution_index")
    if type(index) is not int or index < 0:
        raise ValueError("SayCan execution_index state is invalid")
    rows_raw = request.state.get("execution_results", ())
    if not isinstance(rows_raw, (tuple, list)):
        raise TypeError("SayCan execution_results must be a sequence")
    result_value = thaw_json(request.previous_value)
    rows = list(rows_raw)
    rows.append({
        "execution_index": index,
        "skill": skill,
        "environment_result": result_value,
    })
    return MethodNodeResult(
        value={
            "skill": skill,
            "execution_index": index,
            "environment_result": result_value,
        },
        state_update={
            "execution_index": index + 1,
            "execution_results": tuple(rows),
            "pending_skill": "",
        },
        next_node="execution_route",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    planned = request.state.get("planned_steps", ())
    if not isinstance(planned, (tuple, list)):
        raise TypeError("SayCan planned_steps must be a sequence")
    executable = _executable_steps(request.state)
    rows = request.state.get("execution_results", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("SayCan execution_results must be a sequence")
    return MethodNodeResult(
        value={
            "source_commit": SAYCAN_PAPER_CODE_COMMIT,
            "planned_steps": tuple(planned),
            "executable_steps": executable,
            "planning_calls": request.state.get("planning_calls"),
            "terminated_by_done": (
                request.state.get("terminated_by_done") is True
            ),
            "hit_planning_budget": (
                request.state.get("planning_calls")
                == SAYCAN_FIDELITY.demo_max_tasks
                and request.state.get("terminated_by_done") is not True
            ),
            "executed_skill_count": len(rows),
            "execution_results": tuple(rows),
        }
    )


def build_saycan_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "paper": "Do As I Can, Not As I Say",
        "source_commit": SAYCAN_PAPER_CODE_COMMIT,
        "language_score_space": SAYCAN_FIDELITY.language_score_space,
        "language_score_transform": SAYCAN_FIDELITY.language_score_transform,
        "combined_score_rule": SAYCAN_FIDELITY.combined_score_rule,
        "normalization_rule": SAYCAN_FIDELITY.normalization_rule,
        "selection_rule": SAYCAN_FIDELITY.selection_rule,
        "termination_string": SAYCAN_FIDELITY.termination_string,
        "termination_affordance": SAYCAN_FIDELITY.termination_affordance,
        "max_planning_tasks": SAYCAN_FIDELITY.demo_max_tasks,
        "affordance_semantics": "frozen-before-planning",
        "execution_semantics": "plan-entire-sequence-before-skill-execution",
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="saycan",
            implementation_version=SAYCAN_PAPER_CODE_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="saycan.plan-first-embodied.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(
        identity,
        entrypoint="language_score",
    )
    builder.agent(
        "language_score",
        "saycan.language.score-options",
        _LANGUAGE_AGENT_ID,
        ("select_plan_step",),
        view_handler=_language_view,
        max_visits=SAYCAN_FIDELITY.demo_max_tasks,
    )
    builder.route(
        "select_plan_step",
        "saycan.plan.select",
        _select_plan_step,
        ("language_score", "execution_route"),
        max_visits=SAYCAN_FIDELITY.demo_max_tasks,
    )
    builder.route(
        "execution_route",
        "saycan.execution.route",
        _route_execution,
        ("prepare_skill", "return"),
        max_visits=SAYCAN_FIDELITY.demo_max_tasks + 1,
    )
    builder.compute(
        "prepare_skill",
        "saycan.execution.prepare-skill",
        _prepare_skill,
        ("execute_skill",),
        max_visits=SAYCAN_FIDELITY.demo_max_tasks,
    )
    builder.capability(
        "execute_skill",
        "saycan.execution.embodied-skill",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_skill",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=SAYCAN_FIDELITY.demo_max_tasks,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_skill",
        "saycan.execution.record-skill",
        _record_skill,
        ("execution_route",),
        max_visits=SAYCAN_FIDELITY.demo_max_tasks,
    )
    builder.return_node(
        "return",
        "saycan.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "saycan.language-score-table",
            "saycan.affordance-score-table",
            "saycan.selected-plan",
            "environment.effect",
        ),
        metric_names=(
            "planning_calls",
            "executed_skill_count",
        ),
        artifact_kinds=(
            "saycan_plan",
            "saycan_embodied_trajectory",
        ),
    )


SAYCAN_METHOD_PROGRAM = build_saycan_method_program()


__all__ = [
    "SAYCAN_METHOD_PROGRAM",
    "SayCanLanguageScorerPort",
    "SayCanLanguageScoringAgentLoop",
    "SayCanLanguageScoringRequest",
    "build_saycan_method_program",
    "saycan_initial_state",
]
