from __future__ import annotations

from ..api.completion import AgentCompletionDecision
from ..api.cognition import AgentGoal, AgentObservation, AgentStepReceipt
from ..api.cognition_ports import AgentCompletionPort


def evaluate_agent_completion(
    completion: AgentCompletionPort,
    goal: AgentGoal,
    observation: AgentObservation,
    *,
    planner_finished: bool,
    last_receipt: AgentStepReceipt | None,
) -> AgentCompletionDecision:
    decision = completion.evaluate(
        goal,
        observation,
        planner_finished=planner_finished,
        last_receipt=last_receipt,
    )
    if not isinstance(decision, AgentCompletionDecision):
        raise TypeError("agent completion port must return AgentCompletionDecision")
    return decision


__all__ = ["evaluate_agent_completion"]
