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
    assert report["system_count"] == 172
    assert report["disconnected_system_count"] == 0


def test_environment_family_contracts_are_consumed_by_managed_runtime_catalog() -> None:
    report = _audit_module().build_report()
    by_key = {row["system_key"]: row for row in report["systems"]}
    for key in (
        "environment/embodied",
        "environment/gui",
        "environment/software",
        "environment/web",
    ):
        row = by_key[key]
        assert row["status"] == "production-integrated"
        assert "noetrium_platform.composition.managed_research_services" in (
            row["production_consumers"]
        )
