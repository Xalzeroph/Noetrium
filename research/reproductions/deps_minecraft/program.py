from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
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
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import DEPS_MINECRAFT_FIDELITY
from .source import DEPS_RELEASE_COMMIT


_PLANNER_AGENT_ID = "deps.planner"
_SELECTOR_AGENT_ID = "deps.selector"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_ENVIRONMENT_ACTION_TYPE = "minecraft_goal_controller"


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class DEPSGoal:
    name: str
    goal_type: str
    object: JsonObject
    precondition: JsonObject
    ranking: int
    goal_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "DEPS goal name"))
        object.__setattr__(
            self,
            "goal_type",
            _text(self.goal_type, "DEPS goal type"),
        )
        if not isinstance(self.object, Mapping):
            raise TypeError("DEPS goal object must be an object")
        if not isinstance(self.precondition, Mapping):
            raise TypeError("DEPS goal precondition must be an object")
        if type(self.ranking) is not int or self.ranking < 1:
            raise ValueError("DEPS goal ranking must be positive")
        object.__setattr__(self, "object", freeze_json(self.object))
        object.__setattr__(self, "precondition", freeze_json(self.precondition))
        object.__setattr__(
            self,
            "goal_digest",
            canonical_digest({
                "name": self.name,
                "goal_type": self.goal_type,
                "object": thaw_json(self.object),
                "precondition": thaw_json(self.precondition),
                "ranking": self.ranking,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "name": self.name,
            "goal_type": self.goal_type,
            "object": thaw_json(self.object),
            "precondition": thaw_json(self.precondition),
            "ranking": self.ranking,
            "goal_digest": self.goal_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "DEPSGoal":
        row = _mapping(value, "DEPS goal")
        goal = cls(
            name=_text(row.get("name"), "DEPS goal name"),
            goal_type=_text(row.get("goal_type"), "DEPS goal type"),
            object=_mapping(row.get("object", {}), "DEPS goal object"),
            precondition=_mapping(
                row.get("precondition", {}),
                "DEPS goal precondition",
            ),
            ranking=int(row.get("ranking", 0)),
        )
        supplied = row.get("goal_digest")
        if supplied is not None and supplied != goal.goal_digest:
            raise ValueError("DEPS goal digest mismatch")
        return goal


class DEPSPlannerMode(StrEnum):
    INITIAL_PLAN = "initial_plan"
    FAILURE_DESCRIPTION = "failure_description"
    EXPLANATION = "explanation"
    REPLAN = "replan"


@dataclass(frozen=True, slots=True)
class DEPSPlannerRequest:
    mode: DEPSPlannerMode
    task_question: str
    task_group: str
    dialogue: str
    inventory: tuple[JsonObject, ...] = ()
    failed_goal: DEPSGoal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, DEPSPlannerMode):
            raise TypeError("DEPS planner mode is invalid")
        object.__setattr__(
            self,
            "task_question",
            _text(self.task_question, "DEPS task_question"),
        )
        object.__setattr__(
            self,
            "task_group",
            _text(self.task_group, "DEPS task_group"),
        )
        object.__setattr__(
            self,
            "dialogue",
            _text(self.dialogue, "DEPS dialogue", allow_empty=True),
        )
        if type(self.inventory) is not tuple or any(
            not isinstance(row, Mapping) for row in self.inventory
        ):
            raise TypeError("DEPS inventory must be an object tuple")
        object.__setattr__(
            self,
            "inventory",
            tuple(freeze_json(row) for row in self.inventory),
        )
        if self.failed_goal is not None and not isinstance(
            self.failed_goal, DEPSGoal
        ):
            raise TypeError("DEPS failed_goal must be DEPSGoal")


@dataclass(frozen=True, slots=True)
class DEPSPlannerResponse:
    text: str
    dialogue: str
    goals: tuple[DEPSGoal, ...] = ()
    model_receipt: JsonValue = None
    response_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            _text(self.text, "DEPS planner response", allow_empty=True),
        )
        object.__setattr__(
            self,
            "dialogue",
            _text(self.dialogue, "DEPS planner dialogue", allow_empty=True),
        )
        if type(self.goals) is not tuple or any(
            not isinstance(goal, DEPSGoal) for goal in self.goals
        ):
            raise TypeError("DEPS planner goals must be DEPSGoal tuple")
        object.__setattr__(self, "model_receipt", freeze_json(self.model_receipt))
        object.__setattr__(
            self,
            "response_digest",
            canonical_digest({
                "text": self.text,
                "dialogue": self.dialogue,
                "goals": tuple(goal.goal_digest for goal in self.goals),
                "model_receipt": thaw_json(self.model_receipt),
            }),
        )


@runtime_checkable
class DEPSPlannerPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def generate(
        self,
        request: DEPSPlannerRequest,
        context: ExecutionContext,
    ) -> DEPSPlannerResponse: ...


@dataclass(frozen=True, slots=True)
class DEPSSelectorRequest:
    goals: tuple[DEPSGoal, ...]
    inventory: tuple[JsonObject, ...]
    task_question: str

    def __post_init__(self) -> None:
        if type(self.goals) is not tuple or not self.goals or any(
            not isinstance(goal, DEPSGoal) for goal in self.goals
        ):
            raise ValueError("DEPS selector requires candidate goals")
        if type(self.inventory) is not tuple or any(
            not isinstance(row, Mapping) for row in self.inventory
        ):
            raise TypeError("DEPS selector inventory must be an object tuple")
        object.__setattr__(
            self,
            "task_question",
            _text(self.task_question, "DEPS selector task_question"),
        )


@dataclass(frozen=True, slots=True)
class DEPSGoalSelection:
    selected_index: int
    estimated_steps: tuple[float, ...]
    selector_receipt: JsonValue = None
    selection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.selected_index) is not int or self.selected_index < 0:
            raise ValueError("DEPS selected_index must be non-negative")
        if type(self.estimated_steps) is not tuple or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in self.estimated_steps
        ):
            raise TypeError("DEPS estimated_steps must be numeric tuple")
        object.__setattr__(
            self,
            "estimated_steps",
            tuple(float(value) for value in self.estimated_steps),
        )
        object.__setattr__(
            self,
            "selector_receipt",
            freeze_json(self.selector_receipt),
        )
        object.__setattr__(
            self,
            "selection_digest",
            canonical_digest({
                "selected_index": self.selected_index,
                "estimated_steps": self.estimated_steps,
                "selector_receipt": thaw_json(self.selector_receipt),
            }),
        )


@runtime_checkable
class DEPSSelectorPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def select(
        self,
        request: DEPSSelectorRequest,
        context: ExecutionContext,
    ) -> DEPSGoalSelection: ...


class DEPSPlannerAgentLoop:
    def __init__(self, planner: DEPSPlannerPort) -> None:
        if not isinstance(planner, DEPSPlannerPort):
            raise TypeError("DEPS planner loop requires DEPSPlannerPort")
        require_sha256(planner.identity_digest, "DEPS planner identity_digest")
        self._planner = planner

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "agent": _PLANNER_AGENT_ID,
            "source_commit": DEPS_RELEASE_COMMIT,
            "planner_identity_digest": self._planner.identity_digest,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != _PLANNER_AGENT_ID:
            raise ValueError(f"unexpected DEPS planner id: {request.agent_id}")
        view = _mapping(request.view, "DEPS planner view")
        mode = DEPSPlannerMode(_text(view.get("mode"), "DEPS planner mode"))
        inventory = tuple(
            _mapping(row, "DEPS inventory row")
            for row in _sequence(view.get("inventory", ()), "DEPS inventory")
        )
        failed_goal = (
            None
            if view.get("failed_goal") is None
            else DEPSGoal.from_payload(view.get("failed_goal"))
        )
        response = self._planner.generate(
            DEPSPlannerRequest(
                mode=mode,
                task_question=_text(
                    view.get("task_question"),
                    "DEPS task_question",
                ),
                task_group=_text(view.get("task_group"), "DEPS task_group"),
                dialogue=_text(
                    view.get("dialogue", ""),
                    "DEPS dialogue",
                    allow_empty=True,
                ),
                inventory=inventory,
                failed_goal=failed_goal,
            ),
            request.context,
        )
        if not isinstance(response, DEPSPlannerResponse):
            raise TypeError("DEPS planner must return DEPSPlannerResponse")

        state_update: JsonObject = {
            "dialogue": response.dialogue,
            "last_planner_response_digest": response.response_digest,
            "last_model_receipt": thaw_json(response.model_receipt),
        }
        if mode in (DEPSPlannerMode.INITIAL_PLAN, DEPSPlannerMode.REPLAN):
            goals = response.goals
            if not goals:
                goals = (
                    DEPSGoal(
                        name=DEPS_MINECRAFT_FIDELITY.fallback_goal_name,
                        goal_type=DEPS_MINECRAFT_FIDELITY.fallback_goal_type,
                        object=dict(
                            DEPS_MINECRAFT_FIDELITY.fallback_goal_object
                        ),
                        precondition={},
                        ranking=1,
                    ),
                )
            state_update.update({
                "goal_list": tuple(goal.payload() for goal in goals),
                "last_plan_text": response.text,
            })
        elif mode is DEPSPlannerMode.FAILURE_DESCRIPTION:
            state_update["last_failure_description"] = response.text
        else:
            state_update["last_explanation"] = response.text

        return MethodAgentResult(
            value={
                "mode": mode.value,
                "text": response.text,
                "response_digest": response.response_digest,
            },
            state_update=state_update,
        )


class DEPSSelectorAgentLoop:
    def __init__(self, selector: DEPSSelectorPort) -> None:
        if not isinstance(selector, DEPSSelectorPort):
            raise TypeError("DEPS selector loop requires DEPSSelectorPort")
        require_sha256(selector.identity_digest, "DEPS selector identity_digest")
        self._selector = selector

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "agent": _SELECTOR_AGENT_ID,
            "source_commit": DEPS_RELEASE_COMMIT,
            "selector_identity_digest": self._selector.identity_digest,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != _SELECTOR_AGENT_ID:
            raise ValueError(f"unexpected DEPS selector id: {request.agent_id}")
        view = _mapping(request.view, "DEPS selector view")
        goals = tuple(
            DEPSGoal.from_payload(row)
            for row in _sequence(view.get("goals", ()), "DEPS goals")
        )
        inventory = tuple(
            _mapping(row, "DEPS inventory row")
            for row in _sequence(view.get("inventory", ()), "DEPS inventory")
        )
        selection = self._selector.select(
            DEPSSelectorRequest(
                goals=goals,
                inventory=inventory,
                task_question=_text(
                    view.get("task_question"),
                    "DEPS task_question",
                ),
            ),
            request.context,
        )
        if not isinstance(selection, DEPSGoalSelection):
            raise TypeError("DEPS selector must return DEPSGoalSelection")
        if selection.selected_index >= len(goals):
            raise ValueError("DEPS selector index exceeds candidate goals")
        if len(selection.estimated_steps) not in (0, len(goals)):
            raise ValueError(
                "DEPS selector estimated_steps must be empty or align with goals"
            )
        goal = goals[selection.selected_index]
        return MethodAgentResult(
            value={
                "selected_index": selection.selected_index,
                "selected_goal": goal.payload(),
                "estimated_steps": selection.estimated_steps,
                "selection_digest": selection.selection_digest,
            },
            state_update={
                "selected_index": selection.selected_index,
                "selected_goal": goal.payload(),
                "selector_estimated_steps": selection.estimated_steps,
                "last_selection_digest": selection.selection_digest,
                "last_selector_receipt": thaw_json(
                    selection.selector_receipt
                ),
                "goal_episode_steps": 0,
            },
        )


def deps_minecraft_initial_state(
    *,
    task_id: str,
    task_question: str,
    task_group: str,
    initial_inventory: tuple[JsonObject, ...] = (),
) -> JsonObject:
    if type(initial_inventory) is not tuple or any(
        not isinstance(row, Mapping) for row in initial_inventory
    ):
        raise TypeError("DEPS initial_inventory must be an object tuple")
    return {
        "source_commit": DEPS_RELEASE_COMMIT,
        "task_id": _text(task_id, "DEPS task_id"),
        "task_question": _text(task_question, "DEPS task_question"),
        "task_group": _text(task_group, "DEPS task_group"),
        "inventory": initial_inventory,
        "dialogue": "",
        "goal_list": (),
        "selected_index": None,
        "selected_goal": None,
        "selector_estimated_steps": (),
        "goal_episode_steps": 0,
        "replan_rounds": 0,
        "last_failure_description": "",
        "last_explanation": "",
        "last_plan_text": "",
        "last_goal_execution": {},
        "task_done": False,
        "success": False,
        "trajectory": (),
    }


def deps_should_replan(
    goal: DEPSGoal,
    *,
    goal_episode_steps: int,
    precondition_satisfied: bool,
) -> bool:
    if type(goal_episode_steps) is not int or goal_episode_steps < 0:
        raise ValueError("DEPS goal_episode_steps must be non-negative")
    if type(precondition_satisfied) is not bool:
        raise TypeError("DEPS precondition_satisfied must be boolean")
    if goal.goal_type == "mine":
        return (
            DEPS_MINECRAFT_FIDELITY.mine_replans_on_unsatisfied_precondition
            and not precondition_satisfied
        )
    if goal.goal_type == "craft":
        return (
            goal_episode_steps
            > DEPS_MINECRAFT_FIDELITY.craft_replan_step_threshold
        )
    if goal.goal_type == "smelt":
        return (
            goal_episode_steps
            > DEPS_MINECRAFT_FIDELITY.smelt_replan_step_threshold
        )
    return False


def _planner_view(mode: DEPSPlannerMode):
    def view(request: MethodNodeRequest) -> JsonObject:
        failed = request.state.get("selected_goal")
        return {
            "mode": mode.value,
            "task_question": request.state.get("task_question"),
            "task_group": request.state.get("task_group"),
            "dialogue": request.state.get("dialogue", ""),
            "inventory": request.state.get("inventory", ()),
            "failed_goal": failed,
        }
    return view


def _selector_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "goals": request.state.get("goal_list", ()),
        "inventory": request.state.get("inventory", ()),
        "task_question": request.state.get("task_question"),
    }


def _prepare_goal_execution(request: MethodNodeRequest) -> MethodNodeResult:
    goal = DEPSGoal.from_payload(request.state.get("selected_goal"))
    step = request.state.get("goal_episode_steps", 0)
    if type(step) is not int or step < 0:
        raise ValueError("DEPS goal_episode_steps state is invalid")
    envelope = environment_action_capability_payload(
        _ENVIRONMENT_ACTION_TYPE,
        {
            "task_id": request.state.get("task_id"),
            "task_question": request.state.get("task_question"),
            "goal": goal.payload(),
            "goal_episode_steps": step,
        },
    )
    return MethodNodeResult(
        value={"goal": goal.payload(), "goal_episode_steps": step},
        state_update=envelope,
    )


def _goal_execution_result(value: JsonValue) -> dict[str, JsonValue]:
    result = _mapping(value, "DEPS environment result")
    observation = result.get("observation")
    if not isinstance(observation, Mapping):
        raise TypeError("DEPS environment result requires observation")
    payload = observation.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("DEPS environment observation requires payload")
    execution = payload.get("deps_goal_execution")
    if not isinstance(execution, Mapping):
        raise TypeError(
            "DEPS environment payload requires deps_goal_execution"
        )
    return _mapping(execution, "DEPS goal execution")


def _record_goal_execution(request: MethodNodeRequest) -> MethodNodeResult:
    execution = _goal_execution_result(request.previous_value)
    inventory_raw = execution.get("inventory", ())
    inventory = tuple(
        _mapping(row, "DEPS inventory row")
        for row in _sequence(inventory_raw, "DEPS inventory")
    )
    goal = DEPSGoal.from_payload(request.state.get("selected_goal"))
    prior_steps = request.state.get("goal_episode_steps", 0)
    if type(prior_steps) is not int or prior_steps < 0:
        raise ValueError("DEPS goal_episode_steps state is invalid")
    consumed = execution.get("steps", 1)
    if type(consumed) is not int or consumed < 1:
        raise ValueError("DEPS goal execution steps must be positive")
    goal_steps = prior_steps + consumed
    goal_success = execution.get("goal_success", False)
    task_done = execution.get("task_done", False)
    precondition_satisfied = execution.get(
        "precondition_satisfied",
        True,
    )
    if any(type(value) is not bool for value in (
        goal_success,
        task_done,
        precondition_satisfied,
    )):
        raise TypeError("DEPS execution booleans are invalid")
    replan = deps_should_replan(
        goal,
        goal_episode_steps=goal_steps,
        precondition_satisfied=precondition_satisfied,
    )

    trajectory_raw = request.state.get("trajectory", ())
    if not isinstance(trajectory_raw, (tuple, list)):
        raise TypeError("DEPS trajectory must be a sequence")
    trajectory = list(trajectory_raw)
    trajectory.append({
        "goal": goal.payload(),
        "goal_episode_steps": goal_steps,
        "goal_success": goal_success,
        "task_done": task_done,
        "precondition_satisfied": precondition_satisfied,
        "replan_triggered": replan,
        "provider_receipt": execution.get("provider_receipt"),
    })
    return MethodNodeResult(
        value={
            "goal_success": goal_success,
            "task_done": task_done,
            "replan": replan,
            "goal_episode_steps": goal_steps,
        },
        state_update={
            "inventory": inventory,
            "goal_episode_steps": goal_steps,
            "task_done": task_done,
            "last_goal_execution": execution,
            "trajectory": tuple(trajectory),
        },
        next_node=(
            "record_success"
            if goal_success
            else ("failure_description" if replan else "prepare_execute")
        ),
    )


def _record_success(request: MethodNodeRequest) -> MethodNodeResult:
    goal = DEPSGoal.from_payload(request.state.get("selected_goal"))
    steps = request.state.get("goal_episode_steps", 0)
    if type(steps) is not int or steps < 0:
        raise ValueError("DEPS goal_episode_steps state is invalid")
    dialogue = _text(
        request.state.get("dialogue", ""),
        "DEPS dialogue",
        allow_empty=True,
    )
    if steps > DEPS_MINECRAFT_FIDELITY.success_requires_goal_steps_gt:
        dialogue += f"Human: I succeed on step {goal.ranking}.\n"

    goals = [
        DEPSGoal.from_payload(row)
        for row in _sequence(
            request.state.get("goal_list", ()),
            "DEPS goal_list",
        )
    ]
    selected = request.state.get("selected_index")
    if type(selected) is not int or not 0 <= selected < len(goals):
        raise ValueError("DEPS selected goal index is invalid")
    goals.pop(selected)
    task_done = request.state.get("task_done") is True
    return MethodNodeResult(
        value={
            "goal": goal.payload(),
            "task_done": task_done,
            "remaining_goals": len(goals),
        },
        state_update={
            "dialogue": dialogue,
            "goal_list": tuple(item.payload() for item in goals),
            "selected_index": None,
            "selected_goal": None,
            "goal_episode_steps": 0,
            "success": task_done,
        },
        next_node=(
            "return"
            if task_done
            else ("select_goal" if goals else "failure_description")
        ),
        events=(
            MethodEvent(
                "deps.goal.completed",
                {
                    "goal_digest": goal.goal_digest,
                    "ranking": goal.ranking,
                    "task_done": task_done,
                },
            ),
        ),
    )


def _after_replan(request: MethodNodeRequest) -> MethodNodeResult:
    rounds = request.state.get("replan_rounds", 0)
    if type(rounds) is not int or rounds < 0:
        raise ValueError("DEPS replan_rounds state is invalid")
    rounds += 1
    exhausted = rounds > DEPS_MINECRAFT_FIDELITY.replan_round_limit
    return MethodNodeResult(
        value={
            "replan_rounds": rounds,
            "exhausted": exhausted,
        },
        state_update={"replan_rounds": rounds},
        next_node="return" if exhausted else "select_goal",
        events=(
            MethodEvent(
                "deps.replan.completed",
                {"replan_rounds": rounds, "exhausted": exhausted},
            ),
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = request.state.get("trajectory", ())
    if not isinstance(trajectory, (tuple, list)):
        raise TypeError("DEPS trajectory must be a sequence")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "success": request.state.get("success") is True,
            "task_done": request.state.get("task_done") is True,
            "replan_rounds": request.state.get("replan_rounds", 0),
            "remaining_goals": len(
                _sequence(
                    request.state.get("goal_list", ()),
                    "DEPS goal_list",
                )
            ),
            "trajectory": tuple(trajectory),
        }
    )


def build_deps_minecraft_method_program() -> MethodProgram:
    fidelity = DEPS_MINECRAFT_FIDELITY
    configuration: JsonObject = {
        "source_commit": DEPS_RELEASE_COMMIT,
        "failure_feedback_order": fidelity.failure_feedback_order,
        "craft_replan_step_threshold": fidelity.craft_replan_step_threshold,
        "smelt_replan_step_threshold": fidelity.smelt_replan_step_threshold,
        "replan_round_limit": fidelity.replan_round_limit,
        "replan_break_condition": "rounds > limit",
        "selector_release_complete": fidelity.selector_release_complete,
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
        "environment_action_type": _ENVIRONMENT_ACTION_TYPE,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="deps-minecraft",
            implementation_version=DEPS_RELEASE_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="deps.minecraft.interactive-planning.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="initial_plan")
    builder.agent(
        "initial_plan",
        "deps.plan.initial",
        _PLANNER_AGENT_ID,
        ("select_goal",),
        view_handler=_planner_view(DEPSPlannerMode.INITIAL_PLAN),
    )
    builder.agent(
        "select_goal",
        "deps.select.goal",
        _SELECTOR_AGENT_ID,
        ("prepare_execute",),
        view_handler=_selector_view,
        max_visits=4096,
    )
    builder.compute(
        "prepare_execute",
        "deps.controller.prepare",
        _prepare_goal_execution,
        ("execute_goal",),
        max_visits=4096,
    )
    builder.capability(
        "execute_goal",
        "deps.minecraft.execute-goal",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_execute",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=4096,
        evidence_obligations=("environment.effect",),
    )
    builder.route(
        "record_execute",
        "deps.controller.record",
        _record_goal_execution,
        ("prepare_execute", "failure_description", "record_success"),
        max_visits=4096,
    )
    builder.route(
        "record_success",
        "deps.goal.success",
        _record_success,
        ("select_goal", "failure_description", "return"),
        max_visits=4096,
    )
    builder.agent(
        "failure_description",
        "deps.describe.failure",
        _PLANNER_AGENT_ID,
        ("explain_failure",),
        view_handler=_planner_view(DEPSPlannerMode.FAILURE_DESCRIPTION),
        max_visits=64,
    )
    builder.agent(
        "explain_failure",
        "deps.explain.failure",
        _PLANNER_AGENT_ID,
        ("replan",),
        view_handler=_planner_view(DEPSPlannerMode.EXPLANATION),
        max_visits=64,
    )
    builder.agent(
        "replan",
        "deps.plan.replan",
        _PLANNER_AGENT_ID,
        ("after_replan",),
        view_handler=_planner_view(DEPSPlannerMode.REPLAN),
        max_visits=64,
    )
    builder.route(
        "after_replan",
        "deps.replan.boundary",
        _after_replan,
        ("select_goal", "return"),
        max_visits=64,
    )
    builder.return_node("return", "deps.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "deps.planner.dialogue",
            "deps.selector.receipt",
            "deps.minecraft.trajectory",
            "environment.effect",
        ),
        metric_names=(
            "task_success",
            "replan_rounds",
            "trajectory_steps",
        ),
        artifact_kinds=(
            "deps_planner_dialogue",
            "deps_minecraft_trajectory",
        ),
    )


DEPS_MINECRAFT_METHOD_PROGRAM = build_deps_minecraft_method_program()

__all__ = [
    "DEPSGoal",
    "DEPSGoalSelection",
    "DEPSPlannerAgentLoop",
    "DEPSPlannerMode",
    "DEPSPlannerPort",
    "DEPSPlannerRequest",
    "DEPSPlannerResponse",
    "DEPSSelectorAgentLoop",
    "DEPSSelectorPort",
    "DEPSSelectorRequest",
    "DEPS_MINECRAFT_METHOD_PROGRAM",
    "build_deps_minecraft_method_program",
    "deps_minecraft_initial_state",
    "deps_should_replan",
]
