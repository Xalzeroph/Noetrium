#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
HIERARCHY = ROOT / "noetrium_platform/foundation/governance/system_registry/hierarchy.json"
TARGET_LAYERS = ("foundation", "substrate", "capability")



def module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def semantic_identity(value: object) -> tuple[str | None, str | None]:
    return (
        getattr(value, "__module__", None),
        getattr(value, "__qualname__", getattr(value, "__name__", None)),
    )


def system_roots(catalog: dict[str, dict[str, object]]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for key, row in catalog.items():
        system = key.split("/", 1)[0]
        prefix = str(row["package_prefix"])
        current = roots.get(system)
        if current is None or len(prefix) < len(current):
            roots[system] = prefix
    return roots


def explicit_demands(
    *,
    facades: dict[str, str],
    hierarchy_rows: list[dict[str, object]],
    roots: dict[str, str],
) -> dict[str, set[str]]:
    """Collect only direct-upper-layer demand for each facade.

    A facade exists for one adjacency boundary. Imports from the same layer,
    lower layers, non-adjacent higher layers, application composition, tests,
    or tooling must never enlarge that facade.
    """

    by_facade = {value: key for key, value in facades.items()}
    generated_facades = {facades[layer_id] for layer_id in TARGET_LAYERS}
    system_layer = {
        str(system): str(row["id"])
        for row in hierarchy_rows
        for system in row.get("members", ())
    }
    upper_by_lower = {
        str(row["lower"]): str(row["id"])
        for row in hierarchy_rows
        if row.get("lower") is not None
    }
    composition_layers = tuple(
        (str(row["composition"]), str(row["id"]))
        for row in hierarchy_rows
        if row.get("composition")
    )
    root_rows = tuple(sorted(roots.items(), key=lambda item: -len(item[1])))

    def same_or_child(module: str, prefix: str) -> bool:
        return module == prefix or module.startswith(prefix + ".")

    def source_layer(module: str) -> str | None:
        for system, prefix in root_rows:
            if same_or_child(module, prefix):
                return system_layer.get(system)
        for prefix, layer_id in composition_layers:
            if same_or_child(module, prefix):
                return layer_id
        return None

    demand: dict[str, set[str]] = defaultdict(set)
    for path in (ROOT / "noetrium_platform").rglob("*.py"):
        source = module_name(path)
        if source in generated_facades:
            continue
        layer_id = source_layer(source)
        if layer_id is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module not in by_facade:
                continue
            target_layer = by_facade[node.module]
            if upper_by_lower.get(target_layer) != layer_id:
                continue
            for alias in node.names:
                if alias.name not in {"*", "__all__"}:
                    demand[target_layer].add(alias.name)
    return demand


def resolve_contract(
    *,
    layer_id: str,
    name: str,
    facade_module: object,
    member_apis: tuple[str, ...],
    lower_facade: str | None,
) -> str:
    """Resolve one demanded symbol without requiring the old facade to predeclare it.

    Member-owned contracts win over lower-layer propagation. The current facade
    is consulted only to disambiguate genuinely conflicting same-name symbols.
    """

    candidates: list[tuple[str, object]] = []
    for api_name in member_apis:
        api = importlib.import_module(api_name)
        if hasattr(api, name):
            candidates.append((api_name, getattr(api, name)))

    if candidates:
        identities = {semantic_identity(value) for _, value in candidates}
        if len(identities) == 1:
            return sorted(source for source, _ in candidates)[0]

        if hasattr(facade_module, name):
            target_identity = semantic_identity(getattr(facade_module, name))
            matches = [
                source
                for source, value in candidates
                if semantic_identity(value) == target_identity
            ]
            if matches:
                return sorted(matches)[0]
        raise RuntimeError(
            f"{layer_id} demanded symbol {name} is ambiguous across member APIs: "
            + ", ".join(sorted(source for source, _ in candidates))
        )

    if lower_facade is not None:
        # Propagate unresolved demand downward. The lower layer is processed
        # later and must prove a concrete member-owned source or propagate again.
        return lower_facade

    raise RuntimeError(f"{layer_id} cannot resolve demanded symbol {name}")


def render_layer_facade(
    *,
    layer_id: str,
    sources: dict[str, set[str]],
    exports: set[str],
) -> str:
    lines = [
        '"""Generated explicit layer facade.',
        "",
        "Only contracts deliberately adopted by the next layer are exported.",
        "Do not add wildcard imports or recursive __all__ propagation here.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for source in sorted(sources):
        names = sorted(sources[source])
        lines.append(f"from {source} import (")
        lines.extend(f"    {name}," for name in names)
        lines.append(")")
        lines.append("")
    lines.append("__all__ = (")
    lines.extend(f'    "{name}",' for name in sorted(exports))
    lines.append(")")
    lines.append("")
    lines.append(f'# layer: {layer_id}; generated by scripts/generate_layer_facades.py')
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write and args.check:
        parser.error("--write and --check are mutually exclusive")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    hierarchy = json.loads(HIERARCHY.read_text(encoding="utf-8"))
    rows = hierarchy["layers"]
    by_id = {str(row["id"]): row for row in rows}
    order = [str(row["id"]) for row in rows]
    facades = {layer_id: str(by_id[layer_id]["facade"]) for layer_id in order}
    roots = system_roots(catalog)
    demand = explicit_demands(
        facades=facades,
        hierarchy_rows=rows,
        roots=roots,
    )
    assignments: dict[str, dict[str, str]] = defaultdict(dict)

    for layer_id in reversed(order):
        row = by_id[layer_id]
        facade_name = facades[layer_id]
        facade_module = importlib.import_module(facade_name)
        member_apis = tuple(
            roots[str(system)] + ".api"
            for system in row.get("members", ())
            if str(system) in roots
        )
        lower_id = row.get("lower")
        lower_facade = None if lower_id is None else facades[str(lower_id)]
        for name in sorted(demand[layer_id]):
            source = resolve_contract(
                layer_id=layer_id,
                name=name,
                facade_module=facade_module,
                member_apis=member_apis,
                lower_facade=lower_facade,
            )
            assignments[layer_id][name] = source
            if lower_facade is not None and source == lower_facade:
                demand[str(lower_id)].add(name)

    changed: list[str] = []
    summary: dict[str, object] = {}
    for layer_id in TARGET_LAYERS:
        row = by_id[layer_id]
        sources: dict[str, set[str]] = defaultdict(set)
        for name, source in assignments[layer_id].items():
            sources[source].add(name)
        desired = render_layer_facade(
            layer_id=layer_id,
            sources=sources,
            exports=demand[layer_id],
        )
        module = str(row["facade"])
        path = ROOT.joinpath(*module.split("."))
        if path.is_dir():
            path = path / "__init__.py"
        else:
            path = path.with_suffix(".py")
        current = path.read_text(encoding="utf-8")
        if current != desired:
            changed.append(str(path.relative_to(ROOT)))
            if args.write:
                path.write_text(desired, encoding="utf-8")
        summary[layer_id] = {
            "export_count": len(demand[layer_id]),
            "source_counts": {
                source: len(names) for source, names in sorted(sources.items())
            },
        }

    print(json.dumps({"changed": changed, "layers": summary}, indent=2, sort_keys=True))
    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
