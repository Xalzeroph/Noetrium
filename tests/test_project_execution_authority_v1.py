from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from noetrium import api
from noetrium_platform.product import research_os as research_os_api
from noetrium_platform.composition.operator.project import project_execution_authority
from noetrium_platform.composition.operator.project.project_execution_authority import (
    materialize_project_execution_authorities,
)
from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_study_closure import (
    ResearchStudyProtocolClosureProvider,
)
from tests_runtime_harness.project_execution_fixture import build_study


class _BindingAuthority:
    def resolve(self, definition):
        raise AssertionError("binding resolution is not needed by _study contract")


def test_study_protocol_factory_is_frozen_and_resolved_from_experiment_node() -> None:
    builder = research_os_api.ResearchProgramBuilder("fixture-program")
    builder.study_protocol("study", implementation=build_study)
    builder.experiment("experiment", definitions=("study",))
    portfolio = research_os_api.ResearchPortfolio(
        "fixture-portfolio",
        (builder.freeze(),),
    )
    revision = research_os_api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "fixture",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)
    node = graph.node("fixture-program::experiment")

    provider = ResearchStudyProtocolClosureProvider(_BindingAuthority())
    study = provider._study(node)

    assert study.project_id == "fixture-project"
    assert study.study_id == "fixture-study"
    assert study.repetitions == 1


def test_unresolved_study_protocol_requires_definition_binding_authority() -> None:
    builder = research_os_api.ResearchProgramBuilder("fixture-program")
    builder.protocol("unresolved")
    builder.experiment("experiment", definitions=("unresolved",))
    portfolio = research_os_api.ResearchPortfolio(
        "fixture-portfolio",
        (builder.freeze(),),
    )
    revision = research_os_api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "fixture",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)

    with pytest.raises(RuntimeError, match="definition binding authority"):
        ResearchStudyProtocolClosureProvider(_BindingAuthority())._study(
            graph.node("fixture-program::experiment")
        )


def test_research_execution_authorities_require_complete_experiment_pair() -> None:
    class _Closure:
        def resolve(self, **kwargs):
            raise AssertionError

    with pytest.raises(ValueError, match="requires both"):
        ResearchExecutionAuthorities(
            "a" * 64,
            experiment_closures=_Closure(),
        )


def test_project_authorities_materialize_through_platform_owned_seam(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _Materializer:
        def materialize(self, portfolio):
            assert type(portfolio) is research_os_api.ResearchPortfolio
            return ResearchExecutionAuthorities("0" * 64)

    seen = []

    def build(context, manifest):
        assert type(context) is ResearchExecutionContext
        seen.append(manifest)
        return _Materializer()

    monkeypatch.setattr(
        project_execution_authority,
        "build_local_research_execution_authority_materializer",
        build,
    )

    builder = research_os_api.ResearchProgramBuilder("paper")
    builder.definition(
        "bootstrap",
        kind=research_os_api.ResearchDefinitionKind.CUSTOM,
        config={"kind": "test"},
    )
    builder.node(
        "root",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    portfolio = research_os_api.ResearchPortfolio("paper", (builder.freeze(),))
    runtime = object.__new__(ManagedResearchRuntime)
    runtime.execution_pool = SimpleNamespace(
        resource_competition_policy_digest="f" * 64
    )
    context = ResearchExecutionContext(
        tmp_path,
        runtime,
    )
    manifest = object()

    authorities = materialize_project_execution_authorities(
        context,
        portfolio,
        manifest,
    )
    assert type(authorities) is ResearchExecutionAuthorities
    assert seen == [manifest]
