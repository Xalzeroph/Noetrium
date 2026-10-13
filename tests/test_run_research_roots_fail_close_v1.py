from __future__ import annotations

from noetrium_platform.composition.research_portfolio_execution import (
    ResearchPortfolioExecutionResult,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product.research_control import (
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchExecutionTarget,
    ResearchGraphRevision,
)
from scripts.run_research_roots import _result_exit_code


def _result(state: str) -> ResearchPortfolioExecutionResult:
    revision = ResearchGraphRevision(
        "portfolio",
        "c" * 64,
        message="test",
    )
    target = ResearchExecutionTarget(
        "execution",
        revision,
    )
    receipt = ResearchControlReceipt(
        ResearchControlAction.RUN,
        target,
        state,
        canonical_digest({"state": state}),
        {},
    )
    return ResearchPortfolioExecutionResult(
        "portfolio",
        "c" * 64,
        "d" * 64,
        "execution",
        revision,
        receipt,
    )


def test_execute_process_exit_is_zero_only_for_succeeded_receipt() -> None:
    assert _result_exit_code(_result("succeeded"), mode="execute") == 0
    for state in ("failed", "blocked", "cancelled"):
        assert _result_exit_code(_result(state), mode="execute") != 0


def test_preflight_process_exit_remains_zero() -> None:
    assert _result_exit_code(object(), mode="preflight") == 0
