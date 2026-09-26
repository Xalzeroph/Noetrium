from __future__ import annotations

import json

import pytest

from noetrium import api
from noetrium_platform.composition.operator.project.research_project_codegen import (
    render_research_module,
    render_research_slots,
)


def _blueprint() -> api.ResearchProjectBlueprint:
    a = api.research_os.ResearchProgramBuilder("paper-a")
    a.definition(
        "method",
        kind=api.research_os.ResearchDefinitionKind.METHOD,
    )
    a.node(
        "source",
        kind=api.research_os.ResearchNodeKind.METHOD,
        definitions=("method",),
        outputs=(api.research_os.ResearchOutputSpec("data", api.research_os.ResearchValueKind.DATA),),
    )

    b = api.research_os.ResearchProgramBuilder("paper-b")
    b.definition(
        "metric",
        kind=api.research_os.ResearchDefinitionKind.METRIC,
    )
    b.node(
        "evaluate",
        kind=api.research_os.ResearchNodeKind.EVALUATION,
        definitions=("metric",),
        outputs=(api.research_os.ResearchOutputSpec("score", api.research_os.ResearchValueKind.METRIC),),
    )

    portfolio = api.research_os.ResearchPortfolioBuilder("suite")
    portfolio.program(a.freeze())
    portfolio.program(b.freeze())
    portfolio.depends(
        downstream_program_id="paper-b",
        downstream_node_id="evaluate",
        upstream_program_id="paper-a",
        upstream_node_id="source",
        bindings=(
            api.research_os.ResearchInputBinding(
                "source",
                "data",
                api.research_os.ResearchValueKind.DATA,
            ),
        ),
    )
    return api.ResearchProjectBlueprint(
        portfolio.freeze(),
        (
            api.ResearchDefinitionRef("paper-a", "method"),
            api.ResearchDefinitionRef("paper-b", "metric"),
        ),
    )


def test_blueprint_round_trip_is_canonical_and_preserves_cross_program_graph() -> None:
    blueprint = _blueprint()

    encoded = api.encode_research_project_blueprint(blueprint)
    decoded = api.decode_research_project_blueprint(encoded)

    assert decoded == blueprint
    assert api.encode_research_project_blueprint(decoded) == encoded
    document = json.loads(encoded)
    assert document["schema"] == api.RESEARCH_PROJECT_BLUEPRINT_SCHEMA
    assert len(blueprint.blueprint_digest) == 64
    assert tuple(program.program_id for program in decoded.portfolio.programs) == (
        "paper-a",
        "paper-b",
    )
    assert decoded.portfolio.dependencies[0].upstream == api.research_os.ResearchNodeRef(
        "paper-a",
        "source",
    )
    assert decoded.portfolio.dependencies[0].downstream == api.research_os.ResearchNodeRef(
        "paper-b",
        "evaluate",
    )


def test_codegen_generates_topology_only_and_user_owned_fill_slots() -> None:
    blueprint = _blueprint()

    topology = render_research_module(blueprint)
    slots = render_research_slots(blueprint)

    assert "AUTO-GENERATED Research OS topology" in topology
    assert "api.ResearchPortfolioBuilder('suite')" in topology
    assert "downstream_program_id='paper-b'" in topology
    assert "_slots.paper_a__method" in topology
    assert "_slots.paper_b__metric" in topology
    assert "def paper_a__method" in slots
    assert "def paper_b__metric" in slots
    assert "checkpoint" not in slots
    assert "scheduler" not in slots
    assert "recovery" not in slots.lower()


def _bound_method(payload=None):
    return payload


def test_blueprint_rejects_bound_implementation_truth() -> None:
    builder = api.research_os.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_bound_method)
    builder.node(
        "run",
        kind=api.research_os.ResearchNodeKind.METHOD,
        definitions=("method",),
    )

    with pytest.raises(ValueError, match="implementation-free"):
        api.ResearchProjectBlueprint(
            api.research_os.ResearchPortfolio("suite", (builder.freeze(),)),
            (),
        )


def test_blueprint_rejects_unknown_fill_slot() -> None:
    builder = api.research_os.ResearchProgramBuilder("paper")
    builder.definition(
        "method",
        kind=api.research_os.ResearchDefinitionKind.METHOD,
    )
    builder.node(
        "run",
        kind=api.research_os.ResearchNodeKind.METHOD,
        definitions=("method",),
    )

    with pytest.raises(ValueError, match="unknown definitions"):
        api.ResearchProjectBlueprint(
            api.research_os.ResearchPortfolio("suite", (builder.freeze(),)),
            (api.ResearchDefinitionRef("paper", "missing"),),
        )
