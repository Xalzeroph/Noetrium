from __future__ import annotations

from noetrium import api
from noetrium_platform.composition.research_os import (
    decode_research_portfolio,
    encode_research_portfolio,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_lowering import (
    compile_research_os_lowering,
)
from research.reproductions.chain_of_thought_gsm8k.program import (
    CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM,
)


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("chain-of-thought")
    builder.method_program(
        "method",
        module="research.reproductions.chain_of_thought_gsm8k.program",
        qualname="CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM",
        config={"paper": "neurips-2022"},
    )
    builder.method_node(
        "method",
        definitions=("method",),
    )
    return api.ResearchPortfolio("chain-of-thought-reproduction", (builder.freeze(),))


def test_method_program_symbol_round_trips_through_portfolio_v2_and_lowering() -> None:
    portfolio = _portfolio()

    encoded = encode_research_portfolio(portfolio)
    decoded = decode_research_portfolio(encoded)

    assert decoded == portfolio
    implementation = decoded.programs[0].definitions[0].implementation
    assert type(implementation) is api.ResearchMethodProgramImplementation
    assert implementation.program_digest == CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM.program_digest

    revision = api.ResearchGraphRevision(
        decoded.portfolio_id,
        decoded.portfolio_digest,
        (),
        "method-program binding",
    )
    compiled = compile_research_portfolio_graph(revision, decoded)
    lowering = compile_research_os_lowering(compiled)
    node = lowering.node("chain-of-thought::method")

    assert len(node.method_programs) == 1
    assert node.method_programs[0].program == CHAIN_OF_THOUGHT_GSM8K_METHOD_PROGRAM
    assert node.method_programs[0].program.program_digest == implementation.program_digest
