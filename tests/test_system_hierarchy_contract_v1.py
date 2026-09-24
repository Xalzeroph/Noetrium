from noetrium_platform.foundation.governance.system_registry.api.hierarchy import (
    layer_hierarchy,
)


EXPECTED = {
    "scope": ("scope",),
    "governance": ("governance",),
    "foundation": ("artifact", "resource", "reliability"),
    "substrate": ("portfolio", "data", "runtime"),
    "capability": ("environment", "model", "participant"),
    "execution": ("execution",),
    "experimentation": ("experimentation",),
    "product": ("operator", "research_os"),
}


def test_layer_hierarchy_is_canonical_and_total() -> None:
    hierarchy = layer_hierarchy()
    assert {layer.layer_id: layer.members for layer in hierarchy.layers} == EXPECTED
    assert hierarchy.global_systems == ("platform",)
    assert len(hierarchy.sideplanes) == 1
    sideplane = hierarchy.sideplanes[0]
    assert sideplane.sideplane_id == "observability"
    assert sideplane.system_id == "observability"
    assert sideplane.base_layer_id == "governance"
    assert sideplane.attachment_mode == "application_composition"
    assert hierarchy.is_sideplane_system("observability")
    assert hierarchy.sideplane_for_system("observability") == sideplane
    assert hierarchy.is_global_system("platform")
    assert hierarchy.lower_layer("operator").layer_id == "experimentation"
    assert hierarchy.lower_layer("research_os").layer_id == "experimentation"
    assert hierarchy.lower_layer("experimentation").layer_id == "execution"
    assert hierarchy.lower_layer("execution").layer_id == "capability"
    assert hierarchy.lower_layer("model").layer_id == "substrate"
    assert hierarchy.lower_layer("runtime").layer_id == "foundation"
    assert hierarchy.lower_layer("artifact").layer_id == "governance"
    assert hierarchy.lower_layer("governance").layer_id == "scope"
    assert hierarchy.lower_layer("scope") is None
    assert hierarchy.is_global_contract(
        "noetrium_platform.foundation.kernel.kernel"
    )
