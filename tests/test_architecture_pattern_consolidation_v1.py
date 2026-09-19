from __future__ import annotations

import ast
import json
from pathlib import Path

from noetrium_platform.foundation.governance.system_registry.api import SystemNodeKind

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"


def test_runtime_topology_uses_closed_authority_vocabulary() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert "components" not in catalog
    assert "orchestration" not in catalog
    assert "reference" not in {kind.value for kind in SystemNodeKind}
    assert all(row["node_kind"] != "reference" for row in catalog.values())


def test_execution_command_is_a_facet_not_a_second_truth_authority() -> None:
    command = json.loads(CATALOG.read_text(encoding="utf-8"))["execution/command"]
    assert command["node_kind"] == "facet"
    assert command["canonical_authority"] == "execution"


def test_core_never_imports_public_noetrium_facade() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "noetrium_platform").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "noetrium" or node.module.startswith("noetrium.")
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "noetrium" or alias.name.startswith("noetrium."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{alias.name}")
    assert violations == []
