import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"


def test_registered_parent_ids_are_exact_system_keys() -> None:
    rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    violations = []
    for key, row in rows.items():
        parent = row.get("parent")
        if parent is not None and parent not in rows:
            violations.append((key, parent))
    assert violations == []


def test_registered_system_keys_never_use_module_dot_notation() -> None:
    rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert all("." not in key for key in rows)
