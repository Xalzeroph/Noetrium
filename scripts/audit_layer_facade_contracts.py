#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
HIERARCHY = ROOT / "noetrium_platform/foundation/governance/system_registry/hierarchy.json"
GENERATED_LAYERS = {"foundation", "substrate", "capability"}


def same_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def public_symbols(module_name: str) -> dict[str, object]:
    module = importlib.import_module(module_name)
    names = tuple(getattr(module, "__all__", ()))
    missing = tuple(name for name in names if not hasattr(module, name))
    if missing:
        raise RuntimeError(f"{module_name} declares missing __all__ symbols: {missing}")
    return {name: getattr(module, name) for name in names}


def semantic_identity(value: object) -> tuple[str | None, str | None]:
    return (
        getattr(value, "__module__", None),
        getattr(value, "__qualname__", getattr(value, "__name__", None)),
    )


def implementation_origin(module_name: str) -> bool:
    parts = module_name.split(".")
    if "providers" in parts or "composition" in parts:
        return True
    if "runtime" in parts:
        runtime_index = parts.index("runtime")
        api_indices = [i for i, part in enumerate(parts) if part == "api"]
        if not api_indices or min(api_indices) > runtime_index:
            return True
    return False


def module_path(module_name: str) -> Path:
    path = ROOT.joinpath(*module_name.split("."))
    if path.is_dir():
        return path / "__init__.py"
    return path.with_suffix(".py")


def system_roots(catalog: dict[str, dict[str, object]]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for key, row in catalog.items():
        system = key.split("/", 1)[0]
        prefix = str(row["package_prefix"])
        current = roots.get(system)
        if current is None or len(prefix) < len(current):
            roots[system] = prefix
    return roots


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    hierarchy = json.loads(HIERARCHY.read_text(encoding="utf-8"))
    roots = system_roots(catalog)
    rows = hierarchy["layers"]
    by_id = {str(row["id"]): row for row in rows}
    global_prefixes = tuple(hierarchy.get("global_contract_prefixes", ()))
    violations: list[dict[str, object]] = []

    # System root APIs may expose contracts, never provider/runtime/composition implementations.
    for system, prefix in sorted(roots.items()):
        api_module = prefix + ".api"
        try:
            symbols = public_symbols(api_module)
        except ModuleNotFoundError:
            continue
        for name, value in symbols.items():
            origin = getattr(value, "__module__", None)
            if not isinstance(origin, str):
                continue
            if any(same_or_child(origin, global_prefix) for global_prefix in global_prefixes):
                continue
            if implementation_origin(origin):
                violations.append({
                    "kind": "root_api_implementation_leak",
                    "system": system,
                    "api_module": api_module,
                    "symbol": name,
                    "origin": origin,
                })

    # Layer facades below Product must be explicit: no wildcard imports and no __all__ chaining.
    for row in rows:
        layer_id = str(row["id"])
        if layer_id == "product":
            continue
        facade = str(row["facade"])
        path = module_path(facade)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(alias.name == "*" for alias in node.names):
                violations.append({
                    "kind": "layer_facade_wildcard_import",
                    "layer": layer_id,
                    "facade": facade,
                    "line": node.lineno,
                    "source": node.module,
                })
            if any(alias.name == "__all__" for alias in node.names):
                violations.append({
                    "kind": "layer_facade_recursive_all_import",
                    "layer": layer_id,
                    "facade": facade,
                    "line": node.lineno,
                    "source": node.module,
                })

    # Generated aggregation layers may import only the immediately lower facade or member root APIs.
    for layer_id in GENERATED_LAYERS:
        row = by_id[layer_id]
        facade = str(row["facade"])
        lower_id = str(row["lower"])
        allowed = {str(by_id[lower_id]["facade"])}
        allowed.update(
            roots[str(system)] + ".api"
            for system in row.get("members", ())
            if str(system) in roots
        )
        path = module_path(facade)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.module in {None, "__future__"}:
                continue
            if node.module not in allowed:
                violations.append({
                    "kind": "layer_facade_nonadjacent_source",
                    "layer": layer_id,
                    "facade": facade,
                    "line": node.lineno,
                    "source": node.module,
                    "allowed": sorted(allowed),
                })

        # Each exported object must be identical to one exported by an allowed source.
        actual = public_symbols(facade)
        allowed_symbols: dict[str, list[tuple[str, object]]] = {}
        for source in sorted(allowed):
            try:
                symbols = public_symbols(source)
            except ModuleNotFoundError:
                continue
            for name, value in symbols.items():
                allowed_symbols.setdefault(name, []).append((source, value))
        for name, value in actual.items():
            identity = semantic_identity(value)
            matches = [
                source
                for source, candidate in allowed_symbols.get(name, ())
                if semantic_identity(candidate) == identity
            ]
            if not matches:
                violations.append({
                    "kind": "layer_facade_unowned_export",
                    "layer": layer_id,
                    "facade": facade,
                    "symbol": name,
                    "origin": getattr(value, "__module__", None),
                })

    result = {
        "schema": "noetrium-layer-facade-contract-audit.v2",
        "violation_count": len(violations),
        "violation_kind_counts": {
            kind: sum(1 for row in violations if row["kind"] == kind)
            for kind in sorted({row["kind"] for row in violations})
        },
        "violations": violations,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
