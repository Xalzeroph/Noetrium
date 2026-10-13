#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
COMPONENTS = ROOT / "noetrium_platform/foundation/governance/system_registry/components.json"
HIERARCHY = ROOT / "noetrium_platform/foundation/governance/system_registry/hierarchy.json"


def same_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    components = json.loads(COMPONENTS.read_text(encoding="utf-8"))
    hierarchy = json.loads(HIERARCHY.read_text(encoding="utf-8"))

    system_roots: dict[str, str] = {}
    for key, row in catalog.items():
        system = key.split("/", 1)[0]
        prefix = str(row["package_prefix"])
        current = system_roots.get(system)
        if current is None or len(prefix) < len(current):
            system_roots[system] = prefix

    component_rows = tuple(
        sorted(
            (
                (
                    key,
                    str(row["system"]),
                    str(row["package_prefix"]),
                )
                for key, row in components.items()
            ),
            key=lambda item: -len(item[2]),
        )
    )
    system_rows = tuple(
        sorted(system_roots.items(), key=lambda item: -len(item[1]))
    )
    composition_prefixes = {
        str(row["composition"])
        for row in hierarchy["layers"]
        if row.get("composition")
    }
    application_composition = str(hierarchy["application_composition"])

    def system_for(module: str) -> str | None:
        for system, prefix in system_rows:
            if same_or_child(module, prefix):
                return system
        return None

    def component_for(module: str):
        for key, system, prefix in component_rows:
            if same_or_child(module, prefix):
                return key, system, prefix
        return None

    def is_composition_root(module: str) -> bool:
        if same_or_child(module, application_composition):
            return True
        return any(same_or_child(module, prefix) for prefix in composition_prefixes)

    violations = []
    for path in (ROOT / "noetrium_platform").rglob("*.py"):
        source_module = module_name(path)
        if is_composition_root(source_module):
            continue
        source_system = system_for(source_module)
        if source_system is None:
            continue
        source_component = component_for(source_module)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.ImportFrom) and node.module:
                targets.append(node.module)
            elif isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            for target_module in targets:
                target_component = component_for(target_module)
                if target_component is None:
                    continue
                target_key, target_system, target_prefix = target_component
                if target_system != source_system:
                    continue
                if source_component is not None and source_component[0] == target_key:
                    continue
                required = target_prefix + ".api"
                if target_module == required:
                    continue
                violations.append(
                    {
                        "kind": "component_boundary_penetration",
                        "path": str(path.relative_to(ROOT)),
                        "line": node.lineno,
                        "source_module": source_module,
                        "source_component": (
                            None if source_component is None else source_component[0]
                        ),
                        "target_module": target_module,
                        "target_component": target_key,
                        "required_module": required,
                    }
                )

    counts = Counter(row["kind"] for row in violations)
    document = {
        "schema": "noetrium-component-boundary-audit.v1",
        "violation_count": len(violations),
        "violation_kind_counts": dict(sorted(counts.items())),
        "violations": violations,
    }
    print(json.dumps(document, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
