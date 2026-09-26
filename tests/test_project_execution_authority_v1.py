from __future__ import annotations

import json
import sys
from types import ModuleType
from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.operator.project.project_execution_authority import (
    ProjectExecutionAuthorityConfig,
    load_project_execution_authority_config,
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
    builder = api.ResearchProgramBuilder("fixture-program")
    builder.study_protocol("study", implementation=build_study)
    builder.experiment("experiment", definitions=("study",))
    portfolio = api.ResearchPortfolio(
        "fixture-portfolio",
        (builder.freeze(),),
    )
    revision = api.ResearchGraphRevision(
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


def test_study_protocol_factory_requires_exactly_one_implemented_protocol() -> None:
    builder = api.ResearchProgramBuilder("fixture-program")
    builder.protocol("unresolved")
    builder.experiment("experiment", definitions=("unresolved",))
    portfolio = api.ResearchPortfolio(
        "fixture-portfolio",
        (builder.freeze(),),
    )
    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "fixture",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)

    with pytest.raises(ValueError, match="exactly one implemented PROTOCOL"):
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


def test_project_execution_config_is_strict_and_fail_closed(tmp_path: Path) -> None:
    config = tmp_path / "execution.json"
    config.write_text(
        json.dumps(
            {
                "schema": "noetrium.project-execution-config.v1",
                "authority_factory": "fixture.providers:build",
                "start_background_controllers": False,
                "authority_inputs": {
                    "qualified_model_closure": "/data/models/qualified.json",
                    "world_root": "/data/worlds/sem",
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = load_project_execution_authority_config(config)
    assert loaded == ProjectExecutionAuthorityConfig(
        "fixture.providers:build",
        False,
        (
            ("qualified_model_closure", "/data/models/qualified.json"),
            ("world_root", "/data/worlds/sem"),
        ),
    )

    config.write_text(
        json.dumps(
            {
                "schema": "noetrium.project-execution-config.v1",
                "authority_factory": "fixture.providers:build",
                "unknown": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown fields"):
        load_project_execution_authority_config(config)


def test_project_config_materializes_through_generic_portfolio_seam(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class _Materializer:
        def materialize(self, portfolio):
            assert type(portfolio) is api.ResearchPortfolio
            return ResearchExecutionAuthorities.provider_neutral()

    module_name = "_noetrium_test_project_materializer"
    module = ModuleType(module_name)

    def build(context):
        assert type(context) is ResearchExecutionContext
        assert context.authority_input("qualified_model_closure") == "/tmp/qualified.json"
        assert context.authority_input("missing") is None
        return _Materializer()

    module.build = build
    monkeypatch.setitem(sys.modules, module_name, module)

    builder = api.ResearchProgramBuilder("paper")
    builder.definition(
        "bootstrap",
        kind=api.ResearchDefinitionKind.CUSTOM,
        config={"kind": "test"},
    )
    builder.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    portfolio = api.ResearchPortfolio("paper", (builder.freeze(),))
    context = ResearchExecutionContext(
        tmp_path,
        object.__new__(ManagedResearchRuntime),
        authority_inputs=(("qualified_model_closure", "/tmp/qualified.json"),),
    )

    authorities = materialize_project_execution_authorities(
        module_name + ":build",
        context,
        portfolio,
    )
    assert type(authorities) is ResearchExecutionAuthorities
