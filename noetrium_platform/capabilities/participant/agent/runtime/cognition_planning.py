from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.completion import AgentCompletionDecision, AgentCompletionDisposition
from ..api.cognition import (
    AgentActionSequence,
    AgentCognitionError,
    AgentGoal,
    AgentModeDecision,
    AgentModeDisposition,
    AgentObservation,
    AgentSafetyDecision,
    AgentSafetyDisposition,
    AgentSkillDescription,
    AgentSkillSelection,
    AgentStepReceipt,
)
from ..api.cognition_ports import (
    AgentCompletionPort,
    AgentReactiveModePort,
    AgentSafetySupervisorPort,
    AgentSkillCatalogPort,
    AgentSkillLibraryPort,
)
from .cognition_completion import evaluate_agent_completion


class PlanningDisposition(StrEnum):
    EXECUTE = "execute"
    REPLAN = "replan"
    COMPLETED = "completed"
    TERMINAL_FAILURE = "terminal_failure"
    SAFETY_ABORT = "safety_abort"
    MODE_ABORT = "mode_abort"
    UNGROUNDED_COMPLETION = "ungrounded_completion"


@dataclass(frozen=True, slots=True)
class CognitionPlanningResult:
    disposition: PlanningDisposition
    plan_context: ExecutionContext
    selection: AgentSkillSelection
    sequence: AgentActionSequence
    next_plan_call: int
    completion: AgentCompletionDecision | None = None


class CognitionPlanningPhase:
    """Own skill expansion, safety/mode arbitration and completion grounding."""

    def __init__(
        self,
        *,
        skills: AgentSkillCatalogPort,
        safety: AgentSafetySupervisorPort,
        completion: AgentCompletionPort,
        skill_library: AgentSkillLibraryPort | None,
        reactive_modes: AgentReactiveModePort | None,
        event: Callable[..., None],
        failure: Callable[..., None],
    ) -> None:
        self._skills = skills
        self._safety = safety
        self._completion = completion
        self._skill_library = skill_library
        self._reactive_modes = reactive_modes
        self._event = event
        self._failure = failure
        descriptions = self._skills.describe()
        if not descriptions:
            raise ValueError("agent cognition loop requires a non-empty skill catalog")
        if any(not isinstance(item, AgentSkillDescription) for item in descriptions):
            raise TypeError("agent cognition skill catalog returned an invalid description")
        ids = tuple(description.skill_id for description in descriptions)
        if len(ids) != len(set(ids)):
            raise ValueError("agent cognition skill ids must be unique")
        self._available_skills = descriptions

    @property
    def available_skills(self) -> tuple[AgentSkillDescription, ...]:
        return self._available_skills

    def plan(
        self,
        *,
        selection: AgentSkillSelection,
        goal: AgentGoal,
        observation: AgentObservation,
        plan_context: ExecutionContext,
        plan_call: int,
        last_receipt: AgentStepReceipt | None,
    ) -> CognitionPlanningResult:
        try:
            sequence = self._skills.expand(
                selection,
                observation=observation,
                context=plan_context,
                sequence_id=f"{goal.goal_id}:sequence:{plan_call}",
            )
            if not isinstance(sequence, AgentActionSequence):
                raise TypeError("agent skill catalog returned an invalid action sequence")
            decision = self._safety.review(
                goal, observation, selection, sequence, plan_context
            )
            if not isinstance(decision, AgentSafetyDecision):
                raise TypeError("agent safety supervisor returned an invalid decision")
            next_plan_call = plan_call + 1
            self._event(
                "AGENT_PLAN_SELECTED",
                level="INFO",
                goal_id=goal.goal_id,
                skill_id=selection.skill_id,
                sequence_id=sequence.sequence_id,
                plan_call=next_plan_call,
                disposition=decision.disposition.value,
            )
            if next_plan_call > goal.max_replans + goal.max_steps:
                raise AgentCognitionError(
                    "planning", "AGENT_REPLAN_LIMIT", "agent planner exceeded replan limit"
                )
            if decision.disposition is AgentSafetyDisposition.ABORT:
                return CognitionPlanningResult(
                    PlanningDisposition.SAFETY_ABORT, plan_context, selection, sequence, next_plan_call
                )
            if decision.disposition is AgentSafetyDisposition.REPLAN:
                return CognitionPlanningResult(
                    PlanningDisposition.REPLAN, plan_context, selection, sequence, next_plan_call
                )
            if decision.disposition is AgentSafetyDisposition.PREEMPT:
                if decision.replacement is None:
                    raise AgentCognitionError(
                        "safety", "AGENT_INVALID_PREEMPT", "preempt decision has no replacement"
                    )
                sequence = decision.replacement
            if self._reactive_modes is not None:
                mode_decision = self._reactive_modes.review(
                    goal, observation, selection, sequence, plan_context
                )
                if not isinstance(mode_decision, (AgentModeDecision, type(None))):
                    raise TypeError("agent reactive mode port returned an invalid decision")
                if mode_decision is not None:
                    self._event(
                        "AGENT_MODE_REVIEW",
                        level="INFO" if mode_decision.disposition is AgentModeDisposition.CONTINUE else "WARNING",
                        mode_id=mode_decision.mode_id,
                        disposition=mode_decision.disposition.value,
                    )
                    if mode_decision.disposition is AgentModeDisposition.ABORT:
                        return CognitionPlanningResult(
                            PlanningDisposition.MODE_ABORT, plan_context, selection, sequence, next_plan_call
                        )
                    if mode_decision.disposition is AgentModeDisposition.REPLAN:
                        return CognitionPlanningResult(
                            PlanningDisposition.REPLAN, plan_context, selection, sequence, next_plan_call
                        )
                    if mode_decision.disposition is AgentModeDisposition.PREEMPT:
                        if mode_decision.replacement is None:
                            raise AgentCognitionError(
                                "mode",
                                "AGENT_INVALID_MODE_PREEMPT",
                                "preempting mode decision has no replacement",
                            )
                        sequence = mode_decision.replacement
            if selection.completion_claim or sequence.completion_claim:
                completion = evaluate_agent_completion(
                    self._completion,
                    goal,
                    observation,
                    planner_finished=True,
                    last_receipt=last_receipt,
                )
                if completion.disposition is AgentCompletionDisposition.SUCCEEDED:
                    return CognitionPlanningResult(
                        PlanningDisposition.COMPLETED,
                        plan_context,
                        selection,
                        sequence,
                        next_plan_call,
                        completion,
                    )
                if completion.disposition is AgentCompletionDisposition.FAILED:
                    return CognitionPlanningResult(
                        PlanningDisposition.TERMINAL_FAILURE,
                        plan_context,
                        selection,
                        sequence,
                        next_plan_call,
                        completion,
                    )
                return CognitionPlanningResult(
                    PlanningDisposition.UNGROUNDED_COMPLETION,
                    plan_context,
                    selection,
                    sequence,
                    next_plan_call,
                    completion,
                )
            return CognitionPlanningResult(
                PlanningDisposition.EXECUTE, plan_context, selection, sequence, next_plan_call
            )
        except AgentCognitionError:
            raise
        except BaseException as exc:
            self._failure("AGENT_PLANNING_FAILED", str(exc), phase="planning")
            raise AgentCognitionError(
                "planning", "AGENT_PLANNING_FAILED", str(exc), cause=exc
            ) from exc

    def record_skill(
        self,
        sequence: AgentActionSequence,
        receipts: tuple[AgentStepReceipt, ...],
        *,
        success: bool,
        context: ExecutionContext,
    ) -> None:
        if self._skill_library is None:
            return
        try:
            self._skill_library.record(sequence, receipts, success=success, context=context)
        except BaseException as exc:
            self._failure("AGENT_SKILL_LIBRARY_FAILED", str(exc), phase="memory")
            raise AgentCognitionError(
                "memory", "AGENT_SKILL_LIBRARY_FAILED", str(exc), cause=exc
            ) from exc


__all__ = [
    "CognitionPlanningPhase",
    "CognitionPlanningResult",
    "PlanningDisposition",
]
