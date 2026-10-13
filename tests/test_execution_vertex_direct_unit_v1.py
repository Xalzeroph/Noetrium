"""Executable vertex construction preserves canonical NoetriumUnit identity."""
import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.execution.graph.api.contracts import (
    EXECUTION_VERTEX_SCHEMA,
    execution_vertex,
)


@pytest.mark.parametrize("node_id", ("alpha", "alpha:1", "Test Unicode ??"))
@pytest.mark.parametrize("effectful", (False, True))
@pytest.mark.parametrize("cost", (1, 7, 200))
def test_direct_vertex_canonical_identity_matches_full_public_constructor(
    node_id, effectful, cost,
):
    digest = canonical_digest({"vertex": node_id, "cost": cost})
    source_path = ("graph", node_id)
    attributes = {
        "kind": "execution-vertex",
        "node_id": node_id,
        "semantic_digest": digest,
        "source_path": source_path,
        "effectful": effectful,
        "static_cost": cost,
    }
    expected = NoetriumUnit(
        unit_id=f"execution-vertex:{canonical_digest(attributes)}",
        schemas=(EXECUTION_VERTEX_SCHEMA,),
        attributes=attributes,
    )
    actual = execution_vertex(
        node_id, digest, source_path=source_path,
        effectful=effectful, static_cost=cost,
    )
    assert actual.structural_digest == expected.structural_digest
    assert actual.semantic_digest == expected.semantic_digest
    assert actual.unit_digest == expected.unit_digest
    assert actual.attributes == expected.attributes
    assert actual.schemas == expected.schemas


def test_direct_vertex_keeps_strict_validation():
    digest = canonical_digest({"valid": True})
    with pytest.raises(ValueError):
        execution_vertex(" ", digest)
    with pytest.raises(ValueError):
        execution_vertex("node", "bad-hash")
    with pytest.raises(TypeError):
        execution_vertex("node", digest, source_path=("ok", 1))
    with pytest.raises(TypeError):
        execution_vertex("node", digest, effectful=1)
    with pytest.raises(ValueError):
        execution_vertex("node", digest, static_cost=0)
