"""Reusable single-agent paper-method control loops.

The implementations deliberately leave model prompting and domain actions to
injected downstream ports. A paper can replace one policy or the whole loop.
"""

from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .contracts import (
    ReferenceAgentActionKind,
    ReferenceAgentObservation,
    ReferenceAgentDecision,
    ReferenceAgentDecisionPort,
    ReferenceAgentMessage,
    ReferenceAgentReflectionPort,
    ReferenceAgentRunResult,
    ReferenceAgentSolverPort,
    ReferenceAgentState,
    ReferenceAgentStatus,
    ReferenceAgentToolPort,
    ReferenceAgentPlannerPort,
)
from .runtime import NullReferenceAgentProgress, ReferenceAgentEvent, ReferenceAgentProgressPort


class ReferenceReActMethod:
    """Reason/action/observation loop with an explicit step budget."""

    def __init__(
        self,
        policy: ReferenceAgentDecisionPort,
        tools: ReferenceAgentToolPort,
        *,
        progress: ReferenceAgentProgressPort | None = None,
    ) -> None:
        self._policy = policy
        self._tools = tools
        self._progress = progress or NullReferenceAgentProgress()

    def _checkpoint(self, state: ReferenceAgentState, context: ExecutionContext | None) -> None:
        if context is not None:
            self._progress.checkpoint(state, context=context)

    def _emit(
        self,
        event: ReferenceAgentEvent,
        context: ExecutionContext | None,
    ) -> None:
        if context is not None:
            self._progress.emit(event, context=context)

    def _invoke(self, action):
        invoke_action = getattr(self._tools, "invoke_action", None)
        observation = (
            invoke_action(action)
            if callable(invoke_action)
            else self._tools.invoke(action.name, action.arguments)
        )
        if type(observation) is not ReferenceAgentObservation:
            raise TypeError("agent tool port must return ReferenceAgentObservation")
        if observation.action_digest == action.action_digest:
            return observation
        return ReferenceAgentObservation(
            action.action_digest, observation.content, observation.success,
            capability_id=observation.capability_id,
            result_digest=observation.result_digest,
            artifacts=observation.artifacts,
            effect_receipt=observation.effect_receipt,
            capability_result=observation.capability_result,
        )

    def _failed(
        self,
        task: str,
        state: ReferenceAgentState,
        context: ExecutionContext | None,
        error: Exception,
        observations: list[ReferenceAgentObservation],
    ) -> ReferenceAgentRunResult:
        message = f"{type(error).__name__}: {error}"
        self._emit(ReferenceAgentEvent(
            "failed", context.run_id if context else "local", state.step,
            state.digest, payload={"error": message},
        ), context)
        self._checkpoint(state, context)
        return ReferenceAgentRunResult(
            ReferenceAgentStatus.FAILED, None, state, error=message,
            tool_observations=tuple(observations),
        )

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        context: ExecutionContext | None = None,
        initial_state: ReferenceAgentState | None = None,
    ) -> ReferenceAgentRunResult:
        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("ReAct max_steps must be positive")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError("ReAct context must be an ExecutionContext")
        if initial_state is not None:
            if type(initial_state) is not ReferenceAgentState:
                raise TypeError("ReAct initial_state must be a ReferenceAgentState")
            if initial_state.task != task:
                raise ValueError("ReAct initial_state task must match task")
            state = initial_state
        else:
            state = ReferenceAgentState(task, messages=(ReferenceAgentMessage("user", task),))
        observations: list[ReferenceAgentObservation] = []
        self._checkpoint(state, context)
        for _ in range(max_steps):
            try:
                decision = self._policy.decide(state)
            except Exception as exc:
                return self._failed(task, state, context, exc, observations)
            if type(decision) is not ReferenceAgentDecision:
                return self._failed(
                    task,
                    state,
                    context,
                    TypeError("agent policy must return ReferenceAgentDecision"),
                    observations,
                )
            action = decision.action
            reasoning = decision.reasoning or action.content
            messages = state.messages + (ReferenceAgentMessage("assistant", reasoning),)
            self._emit(ReferenceAgentEvent(
                "decision", context.run_id if context else "local", state.step,
                state.digest, action_digest=action.action_digest,
                payload={"kind": action.kind.value, "name": action.name, "arguments": action.arguments, "reasoning": reasoning},
            ), context)
            if action.kind is ReferenceAgentActionKind.FINAL:
                if not action.content.strip():
                    return self._failed(
                        task,
                        state,
                        context,
                        ValueError("final agent action requires non-empty content"),
                        observations,
                    )
                final_state = ReferenceAgentState(task, messages=messages, scratchpad=state.scratchpad, step=state.step + 1)
                self._emit(ReferenceAgentEvent(
                    "completed", context.run_id if context else "local", final_state.step,
                    final_state.digest, action_digest=action.action_digest,
                    payload={"answer": action.content},
                ), context)
                self._checkpoint(final_state, context)
                return ReferenceAgentRunResult(ReferenceAgentStatus.COMPLETED, action.content, final_state, tool_observations=tuple(observations))
            if action.kind is ReferenceAgentActionKind.TOOL:
                try:
                    observation = self._invoke(action)
                except Exception as exc:
                    observation = ReferenceAgentObservation(
                        action.action_digest, f"{type(exc).__name__}: {exc}", False,
                    )
                observations.append(observation)
                scratchpad = state.scratchpad + (
                    ReferenceAgentMessage("assistant", action.content or action.name),
                    ReferenceAgentMessage("tool", observation.content, action.name),
                )
                state = ReferenceAgentState(task, messages=messages, scratchpad=scratchpad, step=state.step + 1)
                effect = observation.effect_receipt
                effect_payload = None if effect is None else {
                    "effect_id": getattr(effect, "effect_id", ""),
                    "request_digest": getattr(effect, "request_digest", ""),
                    "certainty": getattr(getattr(effect, "certainty", None), "value", ""),
                    "effect_class": getattr(getattr(effect, "effect_class", None), "value", ""),
                    "provider_instance_id": getattr(effect, "provider_instance_id", None),
                    "provider_receipt": getattr(effect, "provider_receipt", None),
                }
                self._emit(ReferenceAgentEvent(
                    "tool_result", context.run_id if context else "local", state.step,
                    state.digest, action_digest=action.action_digest,
                    observation_digest=observation.observation_digest,
                    payload={"success": observation.success, "content": observation.content, "effect": effect_payload},
                ), context)
                self._checkpoint(state, context)
                continue
            if action.kind is ReferenceAgentActionKind.CONTINUE:
                state = ReferenceAgentState(
                    task, messages=messages,
                    scratchpad=state.scratchpad + (ReferenceAgentMessage("assistant", action.content),),
                    step=state.step + 1,
                )
                self._checkpoint(state, context)
                continue
            return self._failed(
                task,
                state,
                context,
                RuntimeError("unsupported ReAct action kind"),
                observations,
            )
        error = f"ReAct reached max_steps={max_steps}"
        self._emit(ReferenceAgentEvent(
            "max_steps", context.run_id if context else "local", state.step,
            state.digest, payload={"max_steps": max_steps},
        ), context)
        self._checkpoint(state, context)
        return ReferenceAgentRunResult(
            ReferenceAgentStatus.MAX_STEPS, None, state,
            error=error,
            tool_observations=tuple(observations),
        )


class ReferenceReflexionMethod:
    """Re-run a bounded base method after an injected reflection."""

    def __init__(
        self,
        base: ReferenceReActMethod,
        reflector: ReferenceAgentReflectionPort,
        *,
        max_attempts: int = 2,
    ) -> None:
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("Reflexion max_attempts must be positive")
        self._base = base
        self._reflector = reflector
        self._max_attempts = max_attempts

    def run(
        self,
        task: str,
        *,
        max_steps: int = 16,
        context: ExecutionContext | None = None,
    ) -> ReferenceAgentRunResult:
        latest = self._base.run(task, max_steps=max_steps, context=context)
        for _ in range(1, self._max_attempts):
            if latest.status is ReferenceAgentStatus.COMPLETED:
                return latest
            reflection = self._reflector.reflect(latest.state, latest)
            reflected_task = f"{task}\nReflection:\n{reflection.content}"
            latest = self._base.run(reflected_task, max_steps=max_steps, context=context)
        return latest


class ReferencePlanAndSolveMethod:
    """Two-phase planning/solving method with durable lifecycle hooks."""

    def __init__(
        self,
        planner: ReferenceAgentPlannerPort,
        solver: ReferenceAgentSolverPort,
        *,
        progress: ReferenceAgentProgressPort | None = None,
    ) -> None:
        if not callable(getattr(planner, "plan", None)):
            raise TypeError("Plan-and-Solve planner must implement plan()")
        if not callable(getattr(solver, "solve", None)):
            raise TypeError("Plan-and-Solve solver must implement solve()")
        self._planner = planner
        self._solver = solver
        self._progress = progress or NullReferenceAgentProgress()

    def _checkpoint(self, state: ReferenceAgentState, context: ExecutionContext | None) -> None:
        if context is not None:
            self._progress.checkpoint(state, context=context)

    def _emit(self, event: ReferenceAgentEvent, context: ExecutionContext | None) -> None:
        if context is not None:
            self._progress.emit(event, context=context)

    def _failed(
        self,
        task: str,
        state: ReferenceAgentState,
        context: ExecutionContext | None,
        error: Exception,
    ) -> ReferenceAgentRunResult:
        message = f"{type(error).__name__}: {error}"
        self._emit(
            ReferenceAgentEvent(
                "failed",
                context.run_id if context else "local",
                state.step,
                state.digest,
                payload={"error": message},
            ),
            context,
        )
        self._checkpoint(state, context)
        return ReferenceAgentRunResult(
            ReferenceAgentStatus.FAILED,
            None,
            state,
            error=message,
        )

    def run(
        self,
        task: str,
        *,
        context: ExecutionContext | None = None,
    ) -> ReferenceAgentRunResult:
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError("Plan-and-Solve context must be an ExecutionContext")
        state = ReferenceAgentState(
            task,
            messages=(ReferenceAgentMessage("user", task),),
        )
        self._checkpoint(state, context)
        run_id = context.run_id if context else "local"
        self._emit(ReferenceAgentEvent("plan_started", run_id, 0, state.digest), context)
        try:
            plan = self._planner.plan(task)
            if (
                type(plan) is not tuple
                or not plan
                or any(type(step) is not str or not step.strip() for step in plan)
            ):
                raise ValueError(
                    "Plan-and-Solve planner must return non-empty string steps"
                )
            planned_state = ReferenceAgentState(
                task,
                messages=state.messages
                + (ReferenceAgentMessage("planner", "\n".join(plan)),),
                scratchpad=tuple(ReferenceAgentMessage("plan", step) for step in plan),
                step=1,
            )
            self._emit(
                ReferenceAgentEvent(
                    "plan_completed",
                    run_id,
                    planned_state.step,
                    planned_state.digest,
                    payload={"steps": plan},
                ),
                context,
            )
            self._checkpoint(planned_state, context)
            state = planned_state
            result = self._solver.solve(task, plan)
            if type(result) is not ReferenceAgentRunResult:
                raise TypeError("Plan-and-Solve solver must return ReferenceAgentRunResult")
            if result.state.task != task:
                raise ValueError("Plan-and-Solve solver changed the task identity")
            self._emit(
                ReferenceAgentEvent(
                    "solve_completed",
                    run_id,
                    result.state.step,
                    result.state.digest,
                    payload={
                        "status": result.status.value,
                        "answer": result.answer,
                    },
                ),
                context,
            )
            self._checkpoint(result.state, context)
            return result
        except Exception as exc:
            return self._failed(task, state, context, exc)


__all__ = ["ReferencePlanAndSolveMethod", "ReferenceReActMethod", "ReferenceReflexionMethod"]
