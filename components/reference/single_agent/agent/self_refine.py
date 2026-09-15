"""Reusable Self-Refine generation/feedback/refinement control loop.

The paper-specific prompting policy is injected through narrow ports. This
component owns only the method control semantics; Noetrium Platform remains the
authority for model invocation, execution context, checkpoints, evidence and
experimentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .contracts import (
    ReferenceAgentMessage,
    ReferenceAgentRunResult,
    ReferenceAgentState,
    ReferenceAgentStatus,
)
from .runtime import NullReferenceAgentProgress, ReferenceAgentEvent, ReferenceAgentProgressPort


@dataclass(frozen=True, slots=True)
class ReferenceSelfRefineFeedback:
    content: str
    accepted: bool = False

    def __post_init__(self) -> None:
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("Self-Refine feedback content must be non-empty")
        if type(self.accepted) is not bool:
            raise TypeError("Self-Refine feedback accepted must be bool")


class ReferenceSelfRefineGeneratorPort(Protocol):
    def generate(self, task: str) -> str: ...


class ReferenceSelfRefineFeedbackPort(Protocol):
    def feedback(
        self,
        task: str,
        candidate: str,
        *,
        iteration: int,
    ) -> ReferenceSelfRefineFeedback: ...


class ReferenceSelfRefineRefinerPort(Protocol):
    def refine(
        self,
        task: str,
        candidate: str,
        feedback: ReferenceSelfRefineFeedback,
        *,
        iteration: int,
    ) -> str: ...


class ReferenceSelfRefineMethod:
    """Bounded generate -> feedback -> refine loop matching Self-Refine semantics."""

    def __init__(
        self,
        generator: ReferenceSelfRefineGeneratorPort,
        feedback: ReferenceSelfRefineFeedbackPort,
        refiner: ReferenceSelfRefineRefinerPort,
        *,
        max_iterations: int = 3,
        progress: ReferenceAgentProgressPort | None = None,
    ) -> None:
        if not callable(getattr(generator, "generate", None)):
            raise TypeError("Self-Refine generator must implement generate()")
        if not callable(getattr(feedback, "feedback", None)):
            raise TypeError("Self-Refine feedback port must implement feedback()")
        if not callable(getattr(refiner, "refine", None)):
            raise TypeError("Self-Refine refiner must implement refine()")
        if type(max_iterations) is not int or max_iterations <= 0:
            raise ValueError("Self-Refine max_iterations must be positive")
        self._generator = generator
        self._feedback = feedback
        self._refiner = refiner
        self._max_iterations = max_iterations
        self._progress = progress or NullReferenceAgentProgress()

    def _checkpoint(self, state: ReferenceAgentState, context: ExecutionContext | None) -> None:
        if context is not None:
            self._progress.checkpoint(state, context=context)

    def _emit(
        self,
        event_type: str,
        state: ReferenceAgentState,
        context: ExecutionContext | None,
        **payload: object,
    ) -> None:
        if context is not None:
            self._progress.emit(
                ReferenceAgentEvent(
                    event_type,
                    context.run_id,
                    state.step,
                    state.digest,
                    payload=payload,
                ),
                context=context,
            )

    @staticmethod
    def _require_text(value: object, *, owner: str) -> str:
        if type(value) is not str or not value.strip():
            raise ValueError(f"Self-Refine {owner} must return non-empty text")
        return value

    def _failed(
        self,
        task: str,
        state: ReferenceAgentState,
        context: ExecutionContext | None,
        error: BaseException,
    ) -> ReferenceAgentRunResult:
        message = f"{type(error).__name__}: {error}"
        self._emit("failed", state, context, error=message)
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
        if type(task) is not str or not task.strip():
            raise ValueError("Self-Refine task must be non-empty")
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError("Self-Refine context must be an ExecutionContext")

        state = ReferenceAgentState(
            task,
            messages=(ReferenceAgentMessage("user", task),),
        )
        self._checkpoint(state, context)
        try:
            candidate = self._require_text(
                self._generator.generate(task),
                owner="generator",
            )
        except BaseException as exc:
            return self._failed(task, state, context, exc)

        state = ReferenceAgentState(
            task,
            messages=state.messages + (ReferenceAgentMessage("assistant", candidate, "candidate"),),
            step=1,
        )
        self._emit("self_refine_generated", state, context, iteration=0)
        self._checkpoint(state, context)

        for iteration in range(self._max_iterations):
            try:
                feedback = self._feedback.feedback(
                    task,
                    candidate,
                    iteration=iteration,
                )
                if not isinstance(feedback, ReferenceSelfRefineFeedback):
                    raise TypeError(
                        "Self-Refine feedback port must return ReferenceSelfRefineFeedback"
                    )
            except BaseException as exc:
                return self._failed(task, state, context, exc)

            state = ReferenceAgentState(
                task,
                messages=state.messages + (
                    ReferenceAgentMessage("critic", feedback.content, "feedback"),
                ),
                scratchpad=state.scratchpad,
                step=state.step + 1,
            )
            self._emit(
                "self_refine_feedback",
                state,
                context,
                iteration=iteration,
                accepted=feedback.accepted,
            )
            self._checkpoint(state, context)

            if feedback.accepted:
                self._emit(
                    "completed",
                    state,
                    context,
                    iteration=iteration,
                    stop_reason="feedback_accepted",
                )
                return ReferenceAgentRunResult(
                    ReferenceAgentStatus.COMPLETED,
                    candidate,
                    state,
                )

            try:
                candidate = self._require_text(
                    self._refiner.refine(
                        task,
                        candidate,
                        feedback,
                        iteration=iteration,
                    ),
                    owner="refiner",
                )
            except BaseException as exc:
                return self._failed(task, state, context, exc)

            state = ReferenceAgentState(
                task,
                messages=state.messages + (
                    ReferenceAgentMessage("assistant", candidate, "refinement"),
                ),
                scratchpad=state.scratchpad,
                step=state.step + 1,
            )
            self._emit("self_refine_refined", state, context, iteration=iteration)
            self._checkpoint(state, context)

        self._emit(
            "completed",
            state,
            context,
            iteration=self._max_iterations,
            stop_reason="iteration_budget",
        )
        return ReferenceAgentRunResult(
            ReferenceAgentStatus.COMPLETED,
            candidate,
            state,
        )


__all__ = [
    "ReferenceSelfRefineFeedback",
    "ReferenceSelfRefineFeedbackPort",
    "ReferenceSelfRefineGeneratorPort",
    "ReferenceSelfRefineMethod",
    "ReferenceSelfRefineRefinerPort",
]
