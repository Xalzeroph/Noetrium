#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INTERNAL_ROOTS = (ROOT / "noetrium", ROOT / "noetrium_platform")
EXTERNAL_GROUPS = {
    "research": (ROOT / "research",),
    "test": (ROOT / "tests",),
    "extension": (
        ROOT / "components",
        ROOT / "orchestration",
        ROOT / "projects",
    ),
    "tooling": (ROOT / "scripts",),
}
GENERATED_PREFIXES = (
    "noetrium.contracts.systems.",
)


def _module(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _sources(roots: tuple[Path, ...]) -> dict[str, Path]:
    rows: dict[str, Path] = {}
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rows[_module(path)] = path
    return rows


def _resolve_from(current: str, path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = current.split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    ascend = node.level - 1
    if ascend > len(package):
        return None
    prefix = package[: len(package) - ascend]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _known_target(candidate: str, known: set[str]) -> str | None:
    if candidate in known:
        return candidate
    parts = candidate.split(".")
    while parts:
        prefix = ".".join(parts)
        if prefix in known:
            return prefix
        parts.pop()
    return None


def _graph(
    sources: dict[str, Path],
) -> tuple[dict[str, set[str]], dict[str, str]]:
    graph: dict[str, set[str]] = {name: set() for name in sources}
    parse_errors: dict[str, str] = {}
    known = set(sources)
    for name, path in sources.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _known_target(alias.name, known)
                    if target is not None:
                        graph[name].add(target)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_from(name, path, node)
                if not base:
                    continue
                target = _known_target(base, known)
                if target is not None:
                    graph[name].add(target)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    child = _known_target(f"{base}.{alias.name}", known)
                    if child is not None:
                        graph[name].add(child)
    return graph, parse_errors


def _external_import_roots(
    roots: tuple[Path, ...],
    known: set[str],
) -> tuple[set[str], dict[str, str]]:
    imported: set[str] = set()
    errors: dict[str, str] = {}
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                errors[path.relative_to(ROOT).as_posix()] = f"{type(exc).__name__}: {exc}"
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = _known_target(alias.name, known)
                        if target is not None:
                            imported.add(target)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    target = _known_target(node.module, known)
                    if target is not None:
                        imported.add(target)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        child = _known_target(f"{node.module}.{alias.name}", known)
                        if child is not None:
                            imported.add(child)
    return imported, errors


def _package_parent_closure(modules: set[str], known: set[str]) -> set[str]:
    result = set(modules)
    for module in tuple(modules):
        parts = module.split(".")
        while len(parts) > 1:
            parts.pop()
            parent = ".".join(parts)
            if parent in known:
                result.add(parent)
    return result


def _reachable(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen: set[str] = set()
    queue = deque(sorted(root for root in roots if root in graph))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(sorted(graph[current] - seen))
    return _package_parent_closure(seen, set(graph))


def _architecture_metadata(module: str) -> bool:
    return (
        module.endswith(".boundary")
        or ".api.boundary" in module
        or module.endswith(".api.boundary")
    )


def _catalog() -> dict[str, object]:
    path = (
        ROOT
        / "noetrium_platform"
        / "foundation"
        / "governance"
        / "system_registry"
        / "catalog.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _hierarchy() -> dict[str, object]:
    path = (
        ROOT
        / "noetrium_platform"
        / "foundation"
        / "governance"
        / "system_registry"
        / "hierarchy.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _root_prefixes(catalog: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, raw in catalog.items():
        if not isinstance(raw, dict):
            continue
        system = key.split("/", 1)[0]
        prefix = raw.get("package_prefix")
        if not isinstance(prefix, str):
            continue
        current = result.get(system)
        if current is None or len(prefix) < len(current):
            result[system] = prefix
    return result


def _owner_for_module(
    module: str,
    catalog: dict[str, object],
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for key, raw in catalog.items():
        if not isinstance(raw, dict):
            continue
        prefix = raw.get("package_prefix")
        if not isinstance(prefix, str):
            continue
        if module == prefix or module.startswith(prefix + "."):
            candidates.append((len(prefix), key.split("/", 1)[0]))
    if not candidates:
        return None
    return max(candidates)[1]


def _layer_for_module(
    module: str,
    catalog: dict[str, object],
    hierarchy: dict[str, object],
) -> str | None:
    layers = hierarchy.get("layers", [])
    if not isinstance(layers, list):
        return None
    owner = _owner_for_module(module, catalog)
    if owner is not None:
        for row in layers:
            if isinstance(row, dict) and owner in row.get("members", []):
                return str(row["id"])
    for row in layers:
        if isinstance(row, dict) and module == row.get("facade"):
            return str(row["id"])
    return None


def _script_roots(known: set[str]) -> set[str]:
    path = ROOT / "pyproject.toml"
    if not path.is_file():
        return set()
    in_scripts = False
    result: set[str] = set()
    assignment = re.compile(r'^[A-Za-z0-9_.-]+\s*=\s*"([^"]+)"\s*$')
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_scripts = line == "[project.scripts]"
            continue
        if not in_scripts:
            continue
        match = assignment.match(line)
        if match is None:
            continue
        module = match.group(1).split(":", 1)[0]
        target = _known_target(module, known)
        if target is not None:
            result.add(target)
    return result


def _kind(module: str) -> str:
    parts = module.split(".")
    if "providers" in parts:
        return "provider"
    if "composition" in parts:
        return "composition"
    if "runtime" in parts:
        return "runtime"
    if "api" in parts or module.endswith(".api"):
        return "api"
    return "other"


def _generated(module: str) -> bool:
    return any(module.startswith(prefix) for prefix in GENERATED_PREFIXES)


def _public_index_lower_layer_sources(
    catalog: dict[str, object],
    hierarchy: dict[str, object],
) -> tuple[str, ...]:
    path = ROOT / "noetrium" / "contracts" / "downstream_capability_catalog.json"
    if not path.is_file():
        return ()
    doc = json.loads(path.read_text(encoding="utf-8"))
    sources: set[str] = set()
    for mapping_name in ("direct_symbol_sources", "ambiguous_symbol_sources"):
        mapping = doc.get(mapping_name, {})
        if not isinstance(mapping, dict):
            continue
        for value in mapping.values():
            if isinstance(value, str):
                sources.add(value)
            elif isinstance(value, list):
                sources.update(str(item) for item in value)
    layers = hierarchy.get("layers", [])
    product_layer = None
    if isinstance(layers, list):
        for row in layers:
            if isinstance(row, dict) and row.get("id") == "product":
                product_layer = "product"
                break
    if product_layer is None:
        return ()
    return tuple(sorted(
        source
        for source in sources
        if (_layer_for_module(source, catalog, hierarchy) not in {None, "product"})
    ))


def audit(extra_roots: tuple[str, ...] = ()) -> dict[str, object]:
    sources = _sources(INTERNAL_ROOTS)
    graph, parse_errors = _graph(sources)
    known = set(sources)
    catalog = _catalog()
    hierarchy = _hierarchy()
    prefixes = _root_prefixes(catalog)

    layers = hierarchy.get("layers", [])
    if not isinstance(layers, list):
        raise RuntimeError("hierarchy layers must be a list")

    layer_facades = {
        str(row["facade"])
        for row in layers
        if isinstance(row, dict) and isinstance(row.get("facade"), str)
    }
    system_root_apis = {
        f"{prefix}.api"
        for prefix in prefixes.values()
        if f"{prefix}.api" in known
    }
    script_roots = _script_roots(known)
    product_roots = {
        "noetrium.api",
        "noetrium.__main__",
        *script_roots,
        *extra_roots,
    }
    product_layer = next(
        (
            str(row["facade"])
            for row in layers
            if isinstance(row, dict) and row.get("id") == "product"
        ),
        None,
    )
    if product_layer is not None:
        product_roots.add(product_layer)

    attachment_roots = system_root_apis | layer_facades | product_roots
    attached = _reachable(graph, attachment_roots)

    external_direct: dict[str, set[str]] = {}
    external_parse_errors: dict[str, dict[str, str]] = {}
    external_reachable: dict[str, set[str]] = {}
    for name, roots in EXTERNAL_GROUPS.items():
        direct, errors = _external_import_roots(roots, known)
        external_direct[name] = direct
        external_parse_errors[name] = errors
        external_reachable[name] = _reachable(graph, direct)

    generated = {name for name in sources if _generated(name)}
    metadata = {name for name in sources if _architecture_metadata(name)}
    unattached = set(sources) - attached - generated - metadata
    any_external = set().union(*external_reachable.values()) if external_reachable else set()
    external_only = unattached & any_external
    orphan = unattached - any_external

    research_only = unattached & external_reachable["research"]
    test_only = (
        unattached
        & external_reachable["test"]
        - external_reachable["research"]
        - external_reachable["extension"]
    )
    extension_only = (
        unattached
        & external_reachable["extension"]
        - external_reachable["research"]
    )

    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    isolated = {
        name
        for name in sources
        if not graph[name] and not reverse.get(name)
    }

    layer_member_missing: list[dict[str, str]] = []
    for row in layers:
        if not isinstance(row, dict):
            continue
        facade = row.get("facade")
        members = row.get("members", [])
        if not isinstance(facade, str) or not isinstance(members, list):
            continue
        for member in members:
            root_api = f"{prefixes[str(member)]}.api"
            if root_api not in known:
                layer_member_missing.append({
                    "layer": str(row["id"]),
                    "system": str(member),
                    "reason": "system_root_api_missing",
                    "required_module": root_api,
                })
                continue
            if facade == root_api:
                continue
            if root_api not in graph.get(facade, set()):
                layer_member_missing.append({
                    "layer": str(row["id"]),
                    "system": str(member),
                    "reason": "layer_facade_does_not_import_system_root_api",
                    "required_module": root_api,
                })

    orphan_by_system = Counter(
        _owner_for_module(name, catalog) or "unowned"
        for name in orphan
    )
    unattached_runtime = {
        name
        for name in unattached
        if _kind(name) in {"runtime", "provider", "composition"}
    }
    lower_public_sources = _public_index_lower_layer_sources(catalog, hierarchy)

    return {
        "schema": "noetrium.hierarchical-reachability-audit.v2",
        "module_count": len(sources),
        "import_edge_count": sum(len(rows) for rows in graph.values()),
        "parse_error_count": len(parse_errors),
        "system_root_api_count": len(system_root_apis),
        "layer_facade_count": len(layer_facades),
        "product_entrypoint_count": len(product_roots),
        "attached_count": len(attached),
        "unattached_count": len(unattached),
        "external_only_count": len(external_only),
        "research_only_count": len(research_only),
        "test_only_count": len(test_only),
        "extension_only_count": len(extension_only),
        "tooling_only_count": len(unattached & external_reachable["tooling"] - external_reachable["research"] - external_reachable["extension"]),
        "architecture_metadata_count": len(metadata),
        "orphan_count": len(orphan),
        "unattached_runtime_provider_composition_count": len(unattached_runtime),
        "isolated_module_count": len(isolated),
        "layer_member_attachment_missing_count": len(layer_member_missing),
        "unified_api_lower_layer_source_count": len(lower_public_sources),
        "orphan_kind_counts": dict(sorted(Counter(_kind(x) for x in orphan).items())),
        "orphan_system_counts": dict(
            sorted(orphan_by_system.items(), key=lambda item: (-item[1], item[0]))
        ),
        "unattached_kind_counts": dict(
            sorted(Counter(_kind(x) for x in unattached).items())
        ),
        "attachment_roots": sorted(attachment_roots),
        "layer_member_attachment_missing": layer_member_missing,
        "orphan_modules": sorted(orphan),
        "external_only_modules": sorted(external_only),
        "research_only_modules": sorted(research_only),
        "test_only_modules": sorted(test_only),
        "extension_only_modules": sorted(extension_only),
        "tooling_only_modules": sorted(unattached & external_reachable["tooling"] - external_reachable["research"] - external_reachable["extension"]),
        "architecture_metadata_modules": sorted(metadata),
        "unattached_runtime_provider_composition": sorted(unattached_runtime),
        "isolated_modules": sorted(isolated),
        "unified_api_lower_layer_sources": list(lower_public_sources),
        "parse_errors": parse_errors,
        "external_parse_errors": external_parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit hierarchical module attachment and downstream exposure"
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = audit(tuple(args.root))
    if args.json:
        args.json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    summary_keys = (
        "module_count",
        "import_edge_count",
        "parse_error_count",
        "system_root_api_count",
        "layer_facade_count",
        "product_entrypoint_count",
        "attached_count",
        "unattached_count",
        "external_only_count",
        "research_only_count",
        "test_only_count",
        "extension_only_count",
        "tooling_only_count",
        "architecture_metadata_count",
        "orphan_count",
        "unattached_runtime_provider_composition_count",
        "isolated_module_count",
        "layer_member_attachment_missing_count",
        "unified_api_lower_layer_source_count",
        "orphan_kind_counts",
        "orphan_system_counts",
    )
    print(json.dumps({key: report[key] for key in summary_keys}, indent=2, sort_keys=True))
    if not args.strict:
        return 0
    return 1 if (
        report["orphan_count"]
        or report["layer_member_attachment_missing_count"]
        or report["unified_api_lower_layer_source_count"]
        or report["parse_error_count"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
