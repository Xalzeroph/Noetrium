import json

import pytest

from noetrium_platform.foundation.kernel.structure import (
    GraphTrigger,
    GraphTriggerKind,
    NoetriumUnit,
    atom_unit,
    endpoint_unit,
    relation_trigger,
    relation_unit,
    structure_unit,
)
from noetrium_platform.foundation.kernel.unit_codec import (
    UNIT_DOCUMENT_SCHEMA,
    decode_unit,
    encode_unit,
)
from noetrium_platform.product.research_unit_codec import (
    decode_research_unit,
    encode_research_unit,
)


def _portfolio() -> NoetriumUnit:
    a = structure_unit(
        "a",
        traits=("research.method",),
        atoms=(atom_unit("cfg", "test.config", {"x": 1}),),
    )
    b = structure_unit("b", traits=("research.method",))
    c = structure_unit("c", traits=("research.method",))
    relation = relation_unit(
        (endpoint_unit("a", None), endpoint_unit("b", None)),
        (endpoint_unit("c", None),),
        "research.flow",
        trigger=GraphTrigger(GraphTriggerKind.QUORUM, 1),
    )
    return structure_unit(
            "p",
            traits=("research.portfolio",),
            members=(a, b, c),
            relations=(relation,),
        )


def test_unit_codec_roundtrip_preserves_exact_and_semantic_identity():
    portfolio = _portfolio()
    decoded = decode_research_unit(encode_research_unit(portfolio))

    assert decoded.semantic_digest == portfolio.semantic_digest
    assert decoded.unit_digest == portfolio.unit_digest
    assert decoded.member("a").atoms[0].attribute("value")["x"] == 1
    relation = decoded.relations[0]
    assert len(relation.units("source")) == 2
    assert relation_trigger(relation).kind is GraphTriggerKind.QUORUM


def test_unit_codec_rejects_legacy_graph_table_shape():
    document = json.loads(encode_research_unit(_portfolio()))
    document.pop("units")
    document.pop("root")
    document["root_graph_index"] = 0
    document["graphs"] = []
    with pytest.raises(ValueError):
        decode_research_unit(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )


def test_unit_codec_rejects_retired_schema_without_compatibility_path():
    document = json.loads(encode_research_unit(_portfolio()))
    assert document["schema"] == UNIT_DOCUMENT_SCHEMA
    document["schema"] = "noetrium.research-portfolio.v14"
    with pytest.raises(ValueError):
        decode_research_unit(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )


def test_unit_codec_does_not_collapse_structures_with_equal_semantic_projection():
    projection = "1" * 64
    left = NoetriumUnit(
        "left",
        schemas=("paper.semantic-equivalence",),
        attributes={"value": 1},
        semantic_projection_digest=projection,
    )
    right = NoetriumUnit(
        "right",
        schemas=("paper.semantic-equivalence",),
        attributes={"value": 2},
        semantic_projection_digest=projection,
    )

    assert left.semantic_digest == right.semantic_digest
    assert left.structural_digest != right.structural_digest
    assert left.unit_digest != right.unit_digest
    assert left != right

    root = NoetriumUnit(
        "root",
        schemas=("paper.root",),
        roles=(("member", (left, right)),),
    )
    decoded = decode_unit(encode_unit(root))
    members = decoded.units("member")

    assert tuple(dict(member.attributes) for member in members) == (
        {"value": 1},
        {"value": 2},
    )
    assert tuple(member.structural_digest for member in members) == (
        left.structural_digest,
        right.structural_digest,
    )
    assert decoded == root


def test_exact_parent_identity_changes_when_semantically_equivalent_child_structure_changes():
    projection = "2" * 64
    child_a = NoetriumUnit(
        "child",
        schemas=("paper.child",),
        attributes={"version": 1},
        semantic_projection_digest=projection,
    )
    child_b = NoetriumUnit(
        "child",
        schemas=("paper.child",),
        attributes={"version": 2},
        semantic_projection_digest=projection,
    )
    parent_a = NoetriumUnit(
        "parent",
        schemas=("paper.parent",),
        roles=(("member", (child_a,)),),
    )
    parent_b = NoetriumUnit(
        "parent",
        schemas=("paper.parent",),
        roles=(("member", (child_b,)),),
    )

    assert child_a.semantic_digest == child_b.semantic_digest
    assert child_a.unit_digest != child_b.unit_digest
    assert parent_a.structural_digest != parent_b.structural_digest
    assert parent_a.unit_digest != parent_b.unit_digest
