from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def owner(module: str, prefixes: tuple[tuple[str, str], ...]) -> str | None:
    for prefix, key in prefixes:
        if module == prefix or module.startswith(prefix + "."):
            return key
    return None


def import_targets(path: Path, current: str) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    targets: set[str] = set()
    package = current.split(".")
    if not path.name == "__init__.py":
        package = package[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: max(0, len(package) - node.level + 1)]
                if node.module:
                    base.extend(node.module.split("."))
                candidate = ".".join(base)
            else:
                candidate = node.module or ""
            if candidate:
                targets.add(candidate)
    return targets


def scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, ()):
            if target not in indices:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            result.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(result, key=lambda row: (-len(row), row))


def audit() -> dict[str, object]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    prefixes = tuple(
        sorted(
            ((row["package_prefix"], key) for key, row in registry.items()),
            key=lambda item: len(item[0]),
            reverse=True,
        )
    )
    module_paths: dict[str, Path] = {}
    node_files: dict[str, list[Path]] = defaultdict(list)
    shell_files: list[str] = []
    total_loc = 0
    shell_loc = 0

    for path in (ROOT / "noetrium_platform").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        module = module_name(path)
        node = owner(module, prefixes)
        if node is None:
            continue
        module_paths[module] = path
        node_files[node].append(path)
        text = path.read_text(encoding="utf-8")
        lines = text.count("\n") + 1
        total_loc += lines
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        definitions = sum(
            isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for item in tree.body
        )
        executable = sum(
            not isinstance(item, (ast.Import, ast.ImportFrom, ast.Expr, ast.Pass))
            for item in tree.body
        )
        if definitions == 0 and executable <= 1:
            shell_files.append(str(path.relative_to(ROOT)))
            shell_loc += lines

    module_graph: dict[str, set[str]] = {name: set() for name in module_paths}
    registry_graph: dict[str, set[str]] = {key: set() for key in registry}
    top_graph: dict[str, set[str]] = defaultdict(set)
    edge_counts: Counter[tuple[str, str]] = Counter()

    for module, path in module_paths.items():
        source_node = owner(module, prefixes)
        if source_node is None:
            continue
        for candidate in import_targets(path, module):
            target = candidate
            while target and target not in module_paths:
                target = target.rpartition(".")[0]
            if not target or target == module:
                continue
            module_graph[module].add(target)
            target_node = owner(target, prefixes)
            if target_node is None or target_node == source_node:
                continue
            registry_graph[source_node].add(target_node)
            edge_counts[(source_node, target_node)] += 1
            source_top = source_node.split("/", 1)[0]
            target_top = target_node.split("/", 1)[0]
            if source_top != target_top:
                top_graph[source_top].add(target_top)

    for key in registry:
        top_graph[key.split("/", 1)[0]]

    registry_cycles = [row for row in scc(registry_graph) if len(row) > 1]
    top_cycles = [row for row in scc(dict(top_graph)) if len(row) > 1]
    same_authority_cycles = [
        row
        for row in registry_cycles
        if len({registry[item].get("canonical_authority") for item in row}) == 1
        and registry[row[0]].get("canonical_authority") is not None
    ]

    node_kind_counts = Counter(row["node_kind"] for row in registry.values())
    shape_counts = Counter(tuple(row.get("shape", ())) for row in registry.values())
    thin_nodes = []
    for key, paths in node_files.items():
        loc = sum(path.read_text(encoding="utf-8").count("\n") + 1 for path in paths)
        shells = sum(str(path.relative_to(ROOT)) in shell_files for path in paths)
        if loc < 160:
            thin_nodes.append(
                {
                    "node": key,
                    "kind": registry[key]["node_kind"],
                    "canonical_authority": registry[key].get("canonical_authority"),
                    "files": len(paths),
                    "loc": loc,
                    "shell_files": shells,
                }
            )

    return {
        "schema": "noetrium-cohesion-coupling-audit.v1",
        "registry_nodes": len(registry),
        "direct_authorities": node_kind_counts["authority"],
        "node_kind_counts": dict(sorted(node_kind_counts.items())),
        "shape_counts": {"|".join(key): value for key, value in shape_counts.items()},
        "registry_owned_files": len(module_paths),
        "registry_owned_loc": total_loc,
        "shell_file_count": len(shell_files),
        "shell_file_ratio": len(shell_files) / max(1, len(module_paths)),
        "shell_loc": shell_loc,
        "shell_loc_ratio": shell_loc / max(1, total_loc),
        "nodes_with_five_or_more_shell_files": sum(
            sum(str(path.relative_to(ROOT)) in shell_files for path in paths) >= 5
            for paths in node_files.values()
        ),
        "thin_nodes": sorted(thin_nodes, key=lambda row: (row["loc"], row["node"])),
        "top_level_sccs": top_cycles,
        "same_authority_registry_sccs": same_authority_cycles,
        "registry_sccs": registry_cycles,
        "highest_cross_node_import_edges": [
            {"source": source, "target": target, "count": count}
            for (source, target), count in edge_counts.most_common(100)
        ],
    }


def main() -> int:
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
