from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from components.reference.single_agent.agent import (
    JsonlReferenceAgentProgress,
    ReferenceAgentStatus,
    ReferenceSelfRefineFeedback,
    ReferenceSelfRefineMethod,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class _Generator:
    def generate(self, task: str) -> str:
        assert task == "answer"
        return "draft"


class _Feedback:
    def feedback(self, task: str, candidate: str, *, iteration: int):
        assert task == "answer"
        if candidate == "draft":
            return ReferenceSelfRefineFeedback("replace the draft", accepted=False)
        assert candidate == "final"
        return ReferenceSelfRefineFeedback("accepted", accepted=True)


class _Refiner:
    def refine(self, task: str, candidate: str, feedback, *, iteration: int) -> str:
        assert task == "answer"
        assert candidate == "draft"
        assert feedback.content == "replace the draft"
        assert iteration == 0
        return "final"


def test_self_refine_runs_generate_feedback_refine_until_accepted() -> None:
    result = ReferenceSelfRefineMethod(
        _Generator(),
        _Feedback(),
        _Refiner(),
        max_iterations=3,
    ).run("answer")

    assert result.status is ReferenceAgentStatus.COMPLETED
    assert result.answer == "final"
    assert tuple(message.name for message in result.state.messages) == (
        None,
        "candidate",
        "feedback",
        "refinement",
        "feedback",
    )
    assert result.state.step == 4


def test_self_refine_iteration_budget_returns_last_complete_refinement() -> None:
    class NeverAccept:
        def feedback(self, task: str, candidate: str, *, iteration: int):
            return ReferenceSelfRefineFeedback(f"feedback-{iteration}", accepted=False)

    class IterativeRefiner:
        def refine(self, task: str, candidate: str, feedback, *, iteration: int) -> str:
            return f"refined-{iteration}"

    result = ReferenceSelfRefineMethod(
        _Generator(),
        NeverAccept(),
        IterativeRefiner(),
        max_iterations=2,
    ).run("answer")

    assert result.status is ReferenceAgentStatus.COMPLETED
    assert result.answer == "refined-1"
    assert result.state.step == 5


def test_self_refine_records_durable_progress_when_context_is_bound() -> None:
    with TemporaryDirectory() as directory:
        progress = JsonlReferenceAgentProgress(Path(directory) / "self-refine.jsonl")
        context = ExecutionContext("run-self-refine", "trace-1", "span-1")
        result = ReferenceSelfRefineMethod(
            _Generator(),
            _Feedback(),
            _Refiner(),
            progress=progress,
        ).run("answer", context=context)

        assert result.status is ReferenceAgentStatus.COMPLETED
        restored = progress.latest_state("run-self-refine")
        assert restored == result.state


def test_self_refine_fails_closed_on_empty_refinement() -> None:
    class OneFeedback:
        def feedback(self, task: str, candidate: str, *, iteration: int):
            return ReferenceSelfRefineFeedback("needs work", accepted=False)

    class EmptyRefiner:
        def refine(self, task: str, candidate: str, feedback, *, iteration: int) -> str:
            return ""

    result = ReferenceSelfRefineMethod(
        _Generator(),
        OneFeedback(),
        EmptyRefiner(),
        max_iterations=1,
    ).run("answer")

    assert result.status is ReferenceAgentStatus.FAILED
    assert result.answer is None
    assert "non-empty text" in (result.error or "")
