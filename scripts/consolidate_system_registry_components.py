from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
COMPONENTS = ROOT / "noetrium_platform/foundation/governance/system_registry/components.json"

RETAIN_KINDS = {"authority", "provider"}


def _load() -> dict[str, dict[str, object]]:
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("system registry must be an object")
    for row in value.values():
        parent = row.get("parent")
        if isinstance(parent, str):
            row["parent"] = parent.replace(".", "/")
    return value


def _owner(
    key: str,
    rows: dict[str, dict[str, object]],
    retained: set[str],
) -> str:
    if key in retained:
        return key
    row = rows[key]
    canonical = row.get("canonical_authority")
    if isinstance(canonical, str) and canonical in retained:
        return canonical
    parent = row.get("parent")
    seen = {key}
    while isinstance(parent, str):
        if parent in seen:
            raise RuntimeError(f"registry parent cycle at {key}")
        seen.add(parent)
        if parent in retained:
            return parent
        parent = rows[parent].get("parent")
    raise RuntimeError(f"no retained system owner for component {key}")


def consolidate() -> tuple[int, int]:
    rows = _load()
    retained = {
        key
        for key, row in rows.items()
        if row.get("parent") is None or row.get("node_kind") in RETAIN_KINDS
    }
    owners = {key: _owner(key, rows, retained) for key in rows}

    component_doc: dict[str, dict[str, object]] = {}
    for key, row in rows.items():
        if key in retained:
            continue
        owner = owners[key]
        component_doc[key] = {
            "system": owner,
            "parent": row.get("parent"),
            "package_prefix": row["package_prefix"],
            "node_kind": row["node_kind"],
            "canonical_authority": row.get("canonical_authority"),
            "owns": row["owns"],
            "must_not_own": row["must_not_own"],
            "shape": row.get("shape", []),
            "downstream_surface": row.get("downstream_surface", "public"),
            "requires": row.get("requires", []),
            "provides": row.get("provides", []),
            "components": row.get("components", []),
        }

    result: dict[str, dict[str, object]] = {}
    for key, original in rows.items():
        if key not in retained:
            continue
        row = dict(original)

        parent = row.get("parent")
        if isinstance(parent, str) and parent not in retained:
            row["parent"] = owners[parent]

        requires: list[str] = []
        for dependency in row.get("requires", []):
            target = dependency if dependency in retained else owners[dependency]
            if target != key and target not in requires:
                requires.append(target)

        provides = list(row.get("provides", []))
        components = list(row.get("components", []))
        for component_key, owner in owners.items():
            if component_key in retained or owner != key:
                continue
            if component_key not in components:
                components.append(component_key)
            component_row = rows[component_key]
            for dependency in component_row.get("requires", []):
                target = dependency if dependency in retained else owners[dependency]
                if target != key and target not in requires:
                    requires.append(target)
            for capability in component_row.get("provides", []):
                if capability not in provides:
                    provides.append(capability)

        row["requires"] = sorted(requires)
        row["provides"] = sorted(provides)
        row["components"] = sorted(set(components))
        result[key] = row

    REGISTRY.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    COMPONENTS.write_text(
        json.dumps(component_doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(rows), len(result)


def main() -> int:
    before, after = consolidate()
    print(json.dumps({
        "schema": "noetrium-system-component-consolidation.v1",
        "before": before,
        "after": after,
        "components": before - after,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
