from __future__ import annotations

from noetrium_platform.composition.research_os import (
    decode_research_portfolio,
    encode_research_portfolio,
)
from noetrium_platform.product.research_os import ResearchPortfolioBuilder


def _finish(call):
    return call.transition(value={"ok": True})


def _configure_method(method):
    method.return_node("finish", "fixture.finish", _finish)


def test_root_program_method_absorbs_lower_method_types() -> None:
    root = ResearchPortfolioBuilder("root-method-fixture")
    paper = root.program("paper")
    paper.method("method", _configure_method, entrypoint="finish")
    paper.method_node("run", definitions=("method",))
    portfolio = root.freeze()

    restored = decode_research_portfolio(encode_research_portfolio(portfolio))
    assert restored.portfolio_digest == portfolio.portfolio_digest
    method = restored.programs[0].definitions[0].implementation
    assert method is not None
    resolved = method.resolve()
    assert resolved.program.graph.entrypoint == "finish"
    assert resolved.memories == ()
