"""Member traversal cardinality is a Unit construction invariant."""
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef


def test_member_count_includes_repeated_paths_not_just_unique_objects():
    leaf = NoetriumUnit("leaf")
    middle = NoetriumUnit(
        "middle", roles=(("member", (leaf, leaf)),),
    )
    root = NoetriumUnit(
        "root", roles=(("member", (middle, middle)),),
    )
    assert leaf.member_walk_count == 1
    assert middle.member_walk_count == 3
    assert root.member_walk_count == 7
    assert len(root.walk()) == root.member_walk_count
    assert len(root.walk("other")) == 1

    reused = NoetriumUnit._from_normalized(
        root.unit_id,
        schemas=root.schemas,
        attributes=root.attributes,
        roles=root.roles,
        semantic_projection_digest=root.semantic_projection_digest,
        structural_digest=root.structural_digest,
    )
    assert reused.member_walk_count == root.member_walk_count
    assert reused.unit_digest == root.unit_digest


def test_deep_member_count_is_iterative_to_query():
    unit = NoetriumUnit("base")
    for index in range(300):
        unit = NoetriumUnit(
            f"level-{index}", roles=(("member", (unit,)),),
        )
    assert unit.member_walk_count == 301
    assert len(unit.walk()) == 301



def test_member_count_preserves_invalid_member_role_type_failure():
    import pytest

    invalid = NoetriumUnit("invalid", roles=(("member", (UnitRef(("child",)),)),))
    with pytest.raises(TypeError, match="not unit-valued"):
        invalid.member_walk_count
    with pytest.raises(TypeError, match="not unit-valued"):
        invalid.walk()
    parent = NoetriumUnit("parent", roles=(("member", (invalid,)),))
    with pytest.raises(TypeError, match="not unit-valued"):
        parent.member_walk_count
