from __future__ import annotations

from noetrium import api
from noetrium_platform.product import research_os as product_research_os
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
    METHOD_CONFIGURER, METHOD_ENTRYPOINT, METHOD_SPEC,
)


def _portfolio() -> product_research_os.ResearchPortfolio:
    root = api.ResearchPortfolioBuilder("chain-of-thought-reproduction")
    builder = root.program("chain-of-thought")
    builder.method(
        "method", METHOD_CONFIGURER,
        method_id=METHOD_SPEC["method_id"],
        entrypoint=METHOD_ENTRYPOINT,
        version=METHOD_SPEC["version"],
        semantic_contract=METHOD_SPEC["semantic_contract"],
        config={"paper": "neurips-2022"},
    )
    builder.method_node("method", definitions=("method",))
    return root.freeze()


def test_method_program_symbol_round_trips_through_portfolio_v2_and_lowering() -> None:
    portfolio = _portfolio()

    encoded = encode_research_portfolio(portfolio)
    decoded = decode_research_portfolio(encoded)

    assert decoded == portfolio
    implementation = decoded.programs[0].definitions[0].implementation
    assert type(implementation) is product_research_os.ResearchMethodImplementation
    resolved = implementation.resolve()
    assert len(implementation.method_digest) == 64
    assert len(resolved.program.program_digest) == 64

    revision = product_research_os.ResearchGraphRevision(
        decoded.portfolio_id,
        decoded.portfolio_digest,
        (),
        "method-program binding",
    )
    compiled = compile_research_portfolio_graph(revision, decoded)
    lowering = compile_research_os_lowering(compiled)
    node = lowering.node("chain-of-thought::method")

    assert len(node.method_programs) == 1
    assert node.method_programs[0].program.program_digest == resolved.program.program_digest
