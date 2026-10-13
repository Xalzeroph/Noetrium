"""Provider-owned observation facets survive the public semantic projection."""
from noetrium_platform.capabilities.environment.api import Observation
from noetrium_platform.composition.environment_capabilities.observation import (
    semantic_observation_payload,
)


def test_authorized_observed_facets_preserved_without_private_diagnostics():
    observed=Observation(
        "snapshot-id", "g"*64,
        {
            "kind":"minecraft_snapshot",
            "decision_view":{
                "kind":"minecraft_decision_view.v1",
                "state":{"inventory":{},"position":{"x":1,"y":64,"z":2}},
            },
            "agent_context_facets":({
                "label":"minecraft.holdings",
                "truth_class":"observed",
                "source":"environment.minecraft.authorized_observation",
                "value":{"inventory_status":"observed_empty","item_counts":{}},
            },),
            "bridge_diagnostics":{"private":"not for agent"},
        },
    )
    projected=semantic_observation_payload(observed)
    payload=projected["payload"]
    assert payload["kind"]=="minecraft_decision_view.v1"
    assert payload["state"]["inventory"]=={}
    assert payload["agent_context_facets"][0]["value"]["inventory_status"]=="observed_empty"
    assert "bridge_diagnostics" not in payload


def test_source_decision_constraints_are_indexed_without_private_facet_scan():
    observed=Observation(
        "snapshot-id", "g"*64,
        {
            "kind":"snapshot",
            "decision_view":{"kind":"decision","state":{}},
            "agent_context_facets":({
                "label":"environment.reference",
                "truth_class":"declared",
                "source":"environment.example",
                "decision_constraint":{
                    "kind":"declared_dependency",
                    "requirements":{"opaque_input":2},
                    "valid_until":"physical_effect",
                },
                "value":{"unresolved_inputs":{"opaque_input":2}},
            },),
        },
    )
    payload=semantic_observation_payload(observed)["payload"]
    assert payload["decision_constraints"] == ({
        "truth_class":"declared",
        "source":"environment.example",
        "constraint":{
            "kind":"declared_dependency",
            "requirements":{"opaque_input":2},
            "valid_until":"physical_effect",
        },
    },)
    assert payload["agent_context_facets"][0]["value"] == {
        "unresolved_inputs":{"opaque_input":2}
    }
