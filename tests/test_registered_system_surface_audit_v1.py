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


def test_unified_api_is_exactly_the_top_level_research_os_surface() -> None:
    from noetrium import api

    assert api.__all__ == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )
    for private_name in (
        "system",
        "search",
        "describe",
        "resolve",
        "owners",
        "AgentMethodSpec",
        "Study",
        "DeploymentStatusIdentity",
        "LocalCommandRunnerPort",
    ):
        assert not hasattr(api, private_name)
