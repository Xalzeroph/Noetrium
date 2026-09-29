from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.product import research_os as research_os_api
from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
    execute_research_portfolio,
    load_research_execution_authority_materializer,
    preflight_research_portfolio,
)


def _bootstrap():
    return None


def _portfolio() -> research_os_api.ResearchPortfolio:
    builder = research_os_api.ResearchProgramBuilder("paper")
    builder.definition(
        "bootstrap",
        kind=research_os_api.ResearchDefinitionKind.CUSTOM,
        implementation=_bootstrap,
    )
    builder.node(
        "root",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    return research_os_api.ResearchPortfolio("paper", (builder.freeze(),))


def test_single_program_and_multi_program_use_cardinality_agnostic_execution(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio()
    authorities = ResearchExecutionAuthorities("0" * 64)

    preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )
    assert preflight.portfolio_id == "paper"
    assert preflight.selected_node_ids == ("paper::root",)

    result = execute_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )
    assert result.portfolio_id == "paper"
    assert result.receipt.state == "succeeded"
    assert result.revision.revision_digest == preflight.revision_digest


def test_portfolio_execution_identity_changes_with_authority_cut(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio()
    left = ResearchExecutionAuthorities("0" * 64)
    right = ResearchExecutionAuthorities("a" * 64)

    left_preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "left",
        authorities=left,
    )
    right_preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "right",
        authorities=right,
    )
    assert left_preflight.revision_digest != right_preflight.revision_digest


def _second_bootstrap():
    return None


def _program(program_id: str, implementation) -> research_os_api.ResearchProgram:
    builder = research_os_api.ResearchProgramBuilder(program_id)
    builder.definition(
        "bootstrap",
        kind=research_os_api.ResearchDefinitionKind.CUSTOM,
        implementation=implementation,
    )
    builder.node(
        "root",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    return builder.freeze()


def test_multiple_programs_use_the_same_portfolio_executor(tmp_path: Path) -> None:
    portfolio = research_os_api.ResearchPortfolio(
        "many",
        (
            _program("p1", _bootstrap),
            _program("p2", _second_bootstrap),
        ),
    )
    authorities = ResearchExecutionAuthorities("0" * 64)

    preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )
    result = execute_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )

    assert preflight.selected_node_ids == ("p1::root", "p2::root")
    assert result.receipt.state == "succeeded"


def test_generic_materializer_loader_is_cardinality_agnostic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sys
    from types import ModuleType

    class _Materializer:
        def materialize(self, portfolio):
            assert type(portfolio) is research_os_api.ResearchPortfolio
            return ResearchExecutionAuthorities("0" * 64)

    module_name = "_noetrium_test_research_execution_materializer"
    module = ModuleType(module_name)
    seen = []

    def build(context):
        seen.append(context)
        return _Materializer()

    module.build = build
    monkeypatch.setitem(sys.modules, module_name, module)
    context = ResearchExecutionContext(
        tmp_path,
        object.__new__(ManagedResearchRuntime),
    )

    materializer = load_research_execution_authority_materializer(
        module_name + ":build",
        context,
    )

    assert isinstance(materializer, _Materializer)
    assert seen == [context]
