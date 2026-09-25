from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _audit_module():
    path = ROOT / "scripts" / "audit_system_integration.py"
    spec = importlib.util.spec_from_file_location(
        "noetrium_system_integration_audit",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_registered_systems_have_no_disconnected_default_runtime_path() -> None:
    report = _audit_module().build_report()
    import json
    catalog = json.loads(
        (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json")
        .read_text(encoding="utf-8")
    )
    assert report["system_count"] == len(catalog)
    assert report["disconnected_system_count"] == 0


def test_environment_family_contracts_are_subsystems_of_environment_authority() -> None:
    from noetrium_platform.foundation.governance.system_registry.api import system_catalog

    by_key = {row.identity.key: row for row in system_catalog()}
    for key in (
        "environment/gui",
        "environment/minecraft",
        "environment/software",
        "environment/web",
    ):
        row = by_key[key]
        assert row.canonical_authority_key == "environment"
        assert row.package_prefix.startswith(
            "noetrium_platform.capabilities.environment."
        )


def test_cross_system_concrete_dependencies_are_composition_only() -> None:
    report = _audit_module().build_report()
    assert report["concrete_bypass_system_count"] == 0
    offenders = {
        row["system_key"]: row["concrete_bypass_consumers"]
        for row in report["systems"]
        if row["concrete_bypass_consumers"]
    }
    assert offenders == {}
