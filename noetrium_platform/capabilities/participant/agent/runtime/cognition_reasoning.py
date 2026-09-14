from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.cognition import (
    AgentActionSummary,
    AgentCognitionError,
    AgentGoal,
    AgentObservation,
    AgentPlanningRequest,
    AgentSkillDescription,
    AgentSkillSelection,
    AgentStepReceipt,
)
from ..api.cognition_ports import AgentPlannerPort
from .cognition_context import CognitionContextSnapshot


FailureSink = Callable[..., None]


@dataclass(frozen=True, slots=True)
class CognitionReasoningResult:
    request: AgentPlanningRequest
    selection: AgentSkillSelection


class CognitionReasoningPhase:
    """Own planner-visible request construction and one typed reasoning call."""

    def __init__(
        self,
        *,
        planner: AgentPlannerPort,
        available_skills: tuple[AgentSkillDescription, ...],
        failure: FailureSink,
    ) -> None:
        self._planner = planner
        self._available_skills = available_skills
        self._failure = failure

    def reason(
        self,
        *,
        goal: AgentGoal,
        observation: AgentObservation,
        context_snapshot: CognitionContextSnapshot,
        plan_context: ExecutionContext,
        step: int,
        plan_call: int,
        prior_actions: tuple[AgentActionSummary, ...],
        last_receipt: AgentStepReceipt | None = None,
    ) -> CognitionReasoningResult:
        try:
            request = AgentPlanningRequest(
                goal=goal,
                observation=observation,
                memory=context_snapshot.memory,
                step=step,
                plan_call=plan_call,
                prior_actions=prior_actions,
                context=plan_context,
                available_skills=self._available_skills,
                retrieved_skills=context_snapshot.retrieved_skills,
                last_receipt=last_receipt,
            )
            selection = self._planner.plan(request)
            if not isinstance(selection, AgentSkillSelection):
                raise TypeError("agent planner returned an invalid skill selection")
            return CognitionReasoningResult(request, selection)
        except AgentCognitionError:
            raise
        except BaseException as exc:
            self._failure("AGENT_REASONING_FAILED", str(exc), phase="reason")
            raise AgentCognitionError(
                "reason", "AGENT_REASONING_FAILED", str(exc), cause=exc
            ) from exc


__all__ = ["CognitionReasoningPhase", "CognitionReasoningResult"]
