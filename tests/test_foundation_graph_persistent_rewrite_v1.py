from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit

from noetrium_platform.foundation.kernel.structure import UnitRef, NoetriumUnit
from noetrium_platform.foundation.kernel.unit_algebra import (
    unit_replace_at_ref,
    unit_rewrite_at_ref,
)


def _tree() -> NoetriumUnit:
    left = structure_unit(
        "left",
        members=(
            structure_unit(
                "inner",
                members=(structure_unit("leaf", parameters={"v": 1}),),
            ),
            structure_unit("stable"),
        ),
    )
    right = structure_unit(
        "right",
        members=(structure_unit("untouched"),),
    )
    return structure_unit("root", members=(left, right))


def test_path_copy_rebuilds_only_target_ancestor_chain() -> None:
    root = _tree()
    old_left = root.member("left")
    old_inner = old_left.member("inner")
    old_right = root.member("right")
    old_stable = old_left.member("stable")

    replacement = structure_unit("leaf", parameters={"v": 2})
    updated = unit_replace_at_ref(
        root,
        UnitRef(("root", "left", "inner", "leaf")),
        replacement,
    )

    assert updated is not root
    assert updated.member("left") is not old_left
    assert updated.member("left").member("inner") is not old_inner
    assert (
        updated.member("left").member("inner").member("leaf")
        is replacement
    )
    assert updated.member("right") is old_right
    assert updated.member("left").member("stable") is old_stable
    assert updated.semantic_digest != root.semantic_digest


def test_rewrite_at_ref_is_iterative_and_identity_preserving_outside_path() -> None:
    depth = 1500
    graph = structure_unit("leaf", parameters={"v": 1})
    path = ["root"]
    for index in range(depth - 1, -1, -1):
        graph = structure_unit(f"g{index:04d}", members=(graph,))
    root = structure_unit("root", members=(graph,))
    path.extend(f"g{index:04d}" for index in range(depth))
    path.append("leaf")

    updated = unit_rewrite_at_ref(
        root,
        UnitRef(tuple(path)),
        lambda current: structure_unit(
            current.unit_id,
            parameters={"v": 2},
        ),
    )

    current = updated
    for child_id in path[1:]:
        current = current.member(child_id)
    assert current.parameters["v"] == 2
