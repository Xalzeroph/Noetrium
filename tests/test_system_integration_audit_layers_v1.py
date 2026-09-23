from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "audit_system_integration.py"
    spec = importlib.util.spec_from_file_location("audit_system_integration_layers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_integration_audit_covers_components_and_internal_facets() -> None:
    report = _module().build_report()
    assert report["system_count"] == 31
    assert report["component_count"] == 66
    assert report["internal_facet_count"] == 33
    assert report["topology_errors"] == ()

    layers = {row["node_key"]: row for row in report["layers"]}
    assert layers["experimentation/lifecycle"]["topology_level"] == "component"
    assert (
        layers["experimentation/lifecycle/study"]["parent_key"]
        == "experimentation/lifecycle"
    )
    assert (
        layers["execution/policy/scheduling"]["parent_key"]
        == "execution/policy"
    )


def test_internal_facet_dependencies_are_real_topology_nodes() -> None:
    report = _module().build_report()
    layer_keys = {row["node_key"] for row in report["layers"]}
    assert "experimentation/lifecycle/study" in layer_keys
    assert "experimentation/lifecycle/experiment" in layer_keys
    assert "experimentation/lifecycle/run" in layer_keys
