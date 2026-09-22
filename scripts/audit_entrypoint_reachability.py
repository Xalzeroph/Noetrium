from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict, deque
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = (ROOT / "noetrium", ROOT / "noetrium_platform")
DEFAULT_ROOTS = (
    "noetrium.api",
    "noetrium_platform.product.operator.composition.research",
    "noetrium_platform.composition.managed_research_runtime",
    "noetrium_platform.composition.managed_research_services",
    "noetrium_platform.research.execution.workflow.api",
    "noetrium_platform.research.experimentation.api.program",
    "noetrium_platform.research.experimentation.run.control.composition.factory",
    "noetrium_platform.research.experimentation.workload.composition",
)


def _module(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _sources() -> dict[str, Path]:
    rows = {}
    for base in PACKAGE_ROOTS:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rows[_module(path)] = path
    return rows


def _resolve_from(current: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = current.split(".")
    current_path = ROOT.joinpath(*package)
    if not current_path.is_dir():
        package = package[:-1]
    ascend = node.level - 1
    if ascend > len(package):
        return None
    prefix = package[: len(package) - ascend]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _graph(sources: dict[str, Path]) -> tuple[dict[str, set[str]], dict[str, str]]:
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
                    candidate = alias.name
                    if candidate in known:
                        graph[name].add(candidate)
                    else:
                        parts = candidate.split(".")
                        while parts:
                            prefix = ".".join(parts)
                            if prefix in known:
                                graph[name].add(prefix)
                                break
                            parts.pop()
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_from(name, node)
                if not base:
                    continue
                if base in known:
                    graph[name].add(base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    child = f"{base}.{alias.name}"
                    if child in known:
                        graph[name].add(child)
    return graph, parse_errors


def _public_sources() -> set[str]:
    catalog_path = ROOT / "noetrium" / "contracts" / "downstream_capability_catalog.json"
    if not catalog_path.is_file():
        return set()
    doc = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows: set[str] = set()
    for mapping_name in ("direct_symbol_sources", "ambiguous_symbol_sources"):
        mapping = doc.get(mapping_name, {})
        if not isinstance(mapping, dict):
            continue
        for value in mapping.values():
            if isinstance(value, str):
                rows.add(value)
            elif isinstance(value, list):
                rows.update(str(item) for item in value)
    systems = doc.get("systems", ())
    if isinstance(systems, list):
        for system in systems:
            if not isinstance(system, dict):
                continue
            facade = system.get("facade_module")
            if isinstance(facade, str):
                rows.add(facade)
            for api_row in system.get("api_modules", ()):
                if isinstance(api_row, dict):
                    module = api_row.get("module")
                    if isinstance(module, str):
                        rows.add(module)
    return rows


def _registry_roots(sources: set[str]) -> set[str]:
    path = ROOT / "noetrium_platform" / "foundation" / "governance" / "system_registry" / "catalog.json"
    if not path.is_file():
        return set()
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: set[str] = set()
    if not isinstance(doc, dict):
        return rows
    for spec in doc.values():
        if not isinstance(spec, dict):
            continue
        prefix = spec.get("package_prefix")
        if not isinstance(prefix, str):
            continue
        if prefix in sources:
            rows.add(prefix)
        for shape in spec.get("shape", ()):
            if not isinstance(shape, str):
                continue
            module = f"{prefix}.{shape}"
            if module in sources:
                rows.add(module)
    return rows


def _reachable(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen: set[str] = set()
    queue = deque(sorted(root for root in roots if root in graph))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(sorted(graph[current] - seen))
    return seen


def _kind(module: str) -> str:
    if ".api" in module or module.endswith(".api"):
        return "api"
    if ".composition" in module or module.endswith(".composition"):
        return "composition"
    if ".runtime" in module or module.endswith(".runtime"):
        return "runtime"
    if ".providers" in module or module.endswith(".providers"):
        return "provider"
    return "other"


def _subsystem(module: str) -> str:
    parts = module.split(".")
    if len(parts) <= 2:
        return module
    if parts[0] == "noetrium_platform":
        return ".".join(parts[:3])
    return ".".join(parts[:2])


def audit(extra_roots: tuple[str, ...] = ()) -> dict[str, object]:
    sources = _sources()
    graph, parse_errors = _graph(sources)
    public = _public_sources()
    registry_roots = _registry_roots(set(sources))
    entry_roots = set(DEFAULT_ROOTS) | set(extra_roots)
    public_reachable = _reachable(graph, {"noetrium.api"} | public)
    product_reachable = _reachable(graph, entry_roots)
    primary_reachable = public_reachable | product_reachable
    registry_reachable = _reachable(graph, registry_roots)
    all_reachable = primary_reachable | registry_reachable
    generated_contracts = {
        name for name in sources if name.startswith("noetrium.contracts.systems.")
    }
    unreachable = sorted(set(sources) - all_reachable - generated_contracts)
    registry_only = sorted(registry_reachable - primary_reachable)

    reverse: dict[str, set[str]] = defaultdict(set)
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    isolated = sorted(
        name for name in sources
        if not graph[name] and not reverse.get(name)
    )
    unreachable_runtime = tuple(
        name for name in unreachable if _kind(name) in {"runtime", "composition"}
    )
    return {
        "schema": "noetrium.entrypoint-reachability-audit.v1",
        "module_count": len(sources),
        "import_edge_count": sum(len(rows) for rows in graph.values()),
        "parse_error_count": len(parse_errors),
        "roots": sorted(entry_roots),
        "generated_public_source_count": len(public),
        "registry_root_count": len(registry_roots),
        "public_reachable_count": len(public_reachable),
        "product_reachable_count": len(product_reachable),
        "primary_reachable_count": len(primary_reachable),
        "registry_reachable_count": len(registry_reachable),
        "registry_only_count": len(registry_only),
        "reachable_union_count": len(all_reachable),
        "unreachable_count": len(unreachable),
        "unreachable_runtime_or_composition_count": len(unreachable_runtime),
        "isolated_module_count": len(isolated),
        "unreachable_kind_counts": dict(sorted(Counter(_kind(x) for x in unreachable).items())),
        "unreachable_subsystem_counts": dict(
            sorted(Counter(_subsystem(x) for x in unreachable).items(), key=lambda item: (-item[1], item[0]))
        ),
        "unreachable_runtime_or_composition": unreachable_runtime,
        "registry_only_modules": registry_only,
        "isolated_modules": isolated,
        "parse_errors": parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit code reachability from real Noetrium product/public entrypoints")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--root", action="append", default=[])
    args = parser.parse_args()
    report = audit(tuple(args.root))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "module_count", "import_edge_count", "parse_error_count",
        "public_reachable_count", "product_reachable_count", "primary_reachable_count",
        "registry_reachable_count", "registry_only_count", "reachable_union_count",
        "unreachable_count", "unreachable_runtime_or_composition_count", "isolated_module_count",
        "unreachable_kind_counts", "unreachable_subsystem_counts",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
