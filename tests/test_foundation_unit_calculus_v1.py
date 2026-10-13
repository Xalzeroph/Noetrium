from noetrium_platform.foundation.kernel.structure import atom_unit, boundary_unit, endpoint_unit, port_unit, relation_unit, structure_unit, type_unit
from noetrium_platform.foundation.kernel.calculus import TransitionLaw
from noetrium_platform.foundation.kernel.structure import (
    GraphPortMode,
    atom_unit,
    boundary_unit,
    endpoint_unit,
    port_unit,
    relation_unit,
    structure_topological_order,
    structure_unit,
    type_unit,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef, role


def test_unit_is_the_only_persistent_structure_carrier():
    value_type = type_unit("test.value")
    boundary = boundary_unit(
        inputs=(port_unit("in", value_type, GraphPortMode.ONE),),
        outputs=(port_unit("out", value_type, GraphPortMode.ONE),),
    )
    atom = atom_unit("constant", "test.value", 1)
    leaf = structure_unit("leaf", traits=("test.leaf",), boundary=boundary, atoms=(atom,))
    relation = relation_unit(
        (endpoint_unit("leaf", "out"),),
        (endpoint_unit(None, "out"),),
        "test.flow",
    )
    root = structure_unit(
        "root",
        traits=("test.root",),
        boundary=boundary,
        members=(leaf,),
        relations=(relation,),
    )
    assert all(
        type(value) is NoetriumUnit
        for value in (value_type, boundary, atom, leaf, relation, root)
    )


def test_unit_reference_supports_sharing_and_cycles_without_object_cycles():
    a = NoetriumUnit(
        "a",
        schemas=("test.unit",),
        roles=(role("next", UnitRef(("b",))),),
    )
    b = NoetriumUnit(
        "b",
        schemas=("test.unit",),
        roles=(role("next", UnitRef(("a",))),),
    )
    root = NoetriumUnit("root", roles=(role("member", a, b),))
    assert root.members == (a, b)
    assert a.refs("next") == (UnitRef(("b",)),)
    assert b.refs("next") == (UnitRef(("a",)),)


def test_structure_semantic_identity_is_alpha_invariant():
    value_type = type_unit("test.value")

    def build(root_id: str, left_id: str, right_id: str, relation_id_value: str):
        left = structure_unit(
            left_id,
            boundary=boundary_unit(
                outputs=(port_unit("out", value_type),)
            ),
        )
        right = structure_unit(
            right_id,
            boundary=boundary_unit(
                inputs=(port_unit("in", value_type),)
            ),
        )
        relation = relation_unit(
            (endpoint_unit(left_id, "out"),),
            (endpoint_unit(right_id, "in"),),
            relation_id_value,
        )
        return structure_unit(
            root_id,
            members=(left, right),
            relations=(relation,),
        )

    left = build("root-a", "left-a", "right-a", "flow-a")
    right = build("root-b", "x", "y", "flow-b")
    assert left.semantic_digest == right.semantic_digest
    assert left.unit_digest != right.unit_digest


def test_structure_order_is_derived_from_relation_units():
    a = structure_unit("a")
    b = structure_unit("b")
    c = structure_unit("c")
    ab = relation_unit(
        (endpoint_unit("a", None),),
        (endpoint_unit("b", None),),
        "flow",
    )
    bc = relation_unit(
        (endpoint_unit("b", None),),
        (endpoint_unit("c", None),),
        "flow",
    )
    root = structure_unit("root", members=(c, a, b), relations=(bc, ab))
    assert structure_topological_order(root, ("flow",)) == ("a", "b", "c")




def test_structure_topological_order_handles_wide_hyperrelations_without_pairwise_expansion():
    sources = tuple(structure_unit(f"s{i:03d}") for i in range(64))
    targets = tuple(structure_unit(f"t{i:03d}") for i in range(64))
    relation = relation_unit(
        tuple(endpoint_unit(node.unit_id, None) for node in sources),
        tuple(endpoint_unit(node.unit_id, None) for node in targets),
        "flow",
    )
    root = structure_unit(
        "wide-hypergraph",
        members=tuple(reversed(targets + sources)),
        relations=(relation,),
    )

    order = structure_topological_order(root, ("flow",))
    position = {node_id: index for index, node_id in enumerate(order)}
    assert len(order) == 128
    assert max(position[node.unit_id] for node in sources) < min(
        position[node.unit_id] for node in targets
    )


def test_wide_duplicate_semantic_hypergraph_is_alpha_invariant():
    def build(prefix: str):
        sources = tuple(structure_unit(f"{prefix}-s-{i:03d}") for i in range(64))
        targets = tuple(structure_unit(f"{prefix}-t-{i:03d}") for i in range(64))
        relation = relation_unit(
            tuple(endpoint_unit(node.unit_id, None) for node in sources),
            tuple(endpoint_unit(node.unit_id, None) for node in targets),
            "flow",
        )
        return structure_unit(
            f"{prefix}-root",
            members=sources + targets,
            relations=(relation,),
        )

    assert build("left").semantic_digest == build("right").semantic_digest


def test_calculus_has_exactly_three_irreducible_transition_laws():
    assert tuple(TransitionLaw) == (
        TransitionLaw.PURE,
        TransitionLaw.AUTHORITY,
        TransitionLaw.PHYSICAL,
    )
