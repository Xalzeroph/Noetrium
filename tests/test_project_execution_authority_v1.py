from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.operator.project.project_execution_authority import (
    ProjectExecutionAuthorities,
    ProjectExecutionAuthorityConfig,
    load_project_execution_authority_config,
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


def test_project_execution_authorities_require_complete_experiment_pair() -> None:
    with pytest.raises(ValueError, match="requires both"):
        ProjectExecutionAuthorities(
            "a" * 64,
            research_bindings=_BindingAuthority(),
        )


def test_project_execution_config_is_strict_and_fail_closed(tmp_path: Path) -> None:
    config = tmp_path / "execution.json"
    config.write_text(
        json.dumps(
            {
                "schema": "noetrium.project-execution-config.v1",
                "authority_factory": "fixture.providers:build",
                "start_background_controllers": False,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_project_execution_authority_config(config)
    assert loaded == ProjectExecutionAuthorityConfig(
        "fixture.providers:build",
        False,
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
