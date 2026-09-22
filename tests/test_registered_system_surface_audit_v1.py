from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_registered_system_surfaces import audit
from scripts.sync_registered_system_shapes import sync_registered_system_shapes

ROOT = Path(__file__).resolve().parents[1]


def test_registered_system_surface_audit_is_clean() -> None:
    rows = audit(ROOT)
    findings = tuple(finding for row in rows for finding in row.findings)
    assert findings == ()


def test_registered_system_shape_check_is_clean() -> None:
    assert sync_registered_system_shapes(ROOT, check=True) == ()


def test_shape_sync_materializes_missing_standard_planes(tmp_path: Path) -> None:
    registry = tmp_path / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    registry.parent.mkdir(parents=True)
    package = tmp_path / "sample_system"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    registry.write_text(
        json.dumps(
            {
                "sample": {
                    "package_prefix": "sample_system",
                    "shape": ["api", "runtime", "providers", "composition"],
                }
            }
        ),
        encoding="utf-8",
    )
    assert sync_registered_system_shapes(tmp_path, check=False) == ()
    assert sync_registered_system_shapes(tmp_path, check=True) == ()
    for plane in ("api", "runtime", "providers", "composition"):
        text = (package / plane / "__init__.py").read_text(encoding="utf-8")
        assert "AUTO-GENERATED registered-system plane stub" in text


def test_unified_api_does_not_expose_registry_collision_escape_hatch() -> None:
    from noetrium import api

    assert not hasattr(api, "system")
    assert api.search("ExperimentPlan") == ()
    assert api.describe("ExperimentPlan") == ()
    try:
        api.resolve("ExperimentPlan")
    except AttributeError:
        pass
    else:
        raise AssertionError("non-Product registry symbols must not escape through unified API")


def test_product_authoring_contracts_are_reachable_through_unified_api() -> None:
    from noetrium import api

    AgentMethodSpec = api.AgentMethodSpec
    Study = api.Study

    assert AgentMethodSpec.__module__.startswith(
        "noetrium_platform.research.execution.workflow.api"
    )
    assert Study.__module__.startswith(
        "noetrium_platform.research.experimentation.study"
    )
    for private_name in ("DeploymentStatusIdentity", "LocalCommandRunnerPort"):
        assert api.owners(private_name) == ()
        assert api.search(private_name) == ()
