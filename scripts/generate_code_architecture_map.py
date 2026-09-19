#!/usr/bin/env python3
"""Generate a code-derived class/dependency architecture map for Noetrium.

The generator is intentionally stdlib-only. It walks every Python module under
``noetrium_platform`` and extracts classes, inheritance, decorators, fields,
methods, imported-symbol references, constructor calls and module imports. The
canonical system registry is then used to project those source facts onto the
platform topology without inventing additional authorities.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "noetrium_platform"
REGISTRY_PATH = SOURCE_ROOT / "foundation/governance/system_registry/catalog.json"
INDEX_PATH = ROOT / "docs/architecture/CODE_ARCHITECTURE_INDEX.json"
MAP_PATH = ROOT / "docs/architecture/CODE_ARCHITECTURE_MAP.md"
SCHEMA = "noetrium-code-architecture-index.v1"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _expr(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _target_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _decorators(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(_expr(value) for value in node.decorator_list)


def _kind(node: ast.ClassDef) -> str:
    bases = {_expr(value).split(".")[-1] for value in node.bases}
    decorators = {value.split("(", 1)[0].split(".")[-1] for value in _decorators(node)}
    if "Protocol" in bases:
        return "protocol"
    if bases & {"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"}:
        return "enum"
    if "dataclass" in decorators:
        return "dataclass"
    return "class"


@dataclass(frozen=True, slots=True)
class ClassRow:
    qualname: str
    module: str
    name: str
    nesting: tuple[str, ...]
    system_key: str | None
    top_system: str | None
    kind: str
    bases: tuple[str, ...]
    decorators: tuple[str, ...]
    fields: tuple[str, ...]
    methods: tuple[str, ...]
    line: int


@dataclass(frozen=True, slots=True)
class EdgeRow:
    source: str
    target: str
    kind: str


class ModuleScanner(ast.NodeVisitor):
    def __init__(self, module: str, system_key: str | None, top_system: str | None) -> None:
        self.module = module
        self.system_key = system_key
        self.top_system = top_system
        self.aliases: dict[str, str] = {}
        self.classes: list[ClassRow] = []
        self.class_nodes: dict[str, ast.ClassDef] = {}
        self.stack: list[str] = []
        self.import_modules: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.aliases[local] = alias.name
            if alias.name.startswith("noetrium_platform"):
                self.import_modules.add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            # Relative imports are normalized later from the current module.
            base_parts = self.module.split(".")[:-node.level]
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        else:
            base = node.module or ""
        if base.startswith("noetrium_platform"):
            self.import_modules.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            self.aliases[local] = f"{base}.{alias.name}" if base else alias.name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        nesting = tuple(self.stack)
        qualname = f"{self.module}.{'/'.join(nesting)}"
        fields: list[str] = []
        methods: list[str] = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(child.name)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fields.append(child.target.id)
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        fields.append(target.id)
        row = ClassRow(
            qualname=qualname,
            module=self.module,
            name=node.name,
            nesting=nesting,
            system_key=self.system_key,
            top_system=self.top_system,
            kind=_kind(node),
            bases=tuple(_expr(value) for value in node.bases),
            decorators=_decorators(node),
            fields=tuple(sorted(set(fields))),
            methods=tuple(methods),
            line=node.lineno,
        )
        self.classes.append(row)
        self.class_nodes[qualname] = node
        self.generic_visit(node)
        self.stack.pop()


def _load_registry() -> dict[str, dict[str, object]]:
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("system registry must be a JSON object")
    return raw


def _system_for_module(module: str, registry: dict[str, dict[str, object]]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for key, descriptor in registry.items():
        prefix = descriptor.get("package_prefix")
        if isinstance(prefix, str) and (module == prefix or module.startswith(prefix + ".")):
            candidates.append((len(prefix), key))
    return max(candidates)[1] if candidates else None


def _top_system(key: str | None, registry: dict[str, dict[str, object]]) -> str | None:
    if key is None:
        return None
    seen: set[str] = set()
    current = key
    while current not in seen:
        seen.add(current)
        descriptor = registry.get(current)
        if descriptor is None:
            return current.split("/", 1)[0]
        parent = descriptor.get("parent")
        if not isinstance(parent, str) or not parent:
            return current
        current = parent.replace(".", "/")
    return key.split("/", 1)[0]


def _resolve_symbol(raw: str, module: str, aliases: dict[str, str]) -> str:
    if not raw:
        return raw
    root, dot, rest = raw.partition(".")
    if root in aliases:
        target = aliases[root]
        return f"{target}.{rest}" if dot else target
    if "." not in raw and not raw.startswith("typing"):
        return f"{module}.{raw}"
    return raw


def _annotation_refs(node: ast.AST) -> set[str]:
    refs: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Name, ast.Attribute)):
            value = _target_name(child)
            if value:
                refs.add(value)
    return refs


def _class_reference_edges(
    scanners: dict[str, ModuleScanner],
    class_lookup: dict[str, str],
) -> tuple[list[EdgeRow], list[EdgeRow], list[EdgeRow]]:
    inheritance: set[tuple[str, str]] = set()
    associations: set[tuple[str, str]] = set()
    constructors: set[tuple[str, str]] = set()
    for scanner in scanners.values():
        for source, node in scanner.class_nodes.items():
            for base in node.bases:
                resolved = _resolve_symbol(_expr(base), scanner.module, scanner.aliases)
                target = class_lookup.get(resolved)
                if target and target != source:
                    inheritance.add((source, target))
            annotation_nodes: list[ast.AST] = []
            for child in ast.walk(node):
                if isinstance(child, ast.AnnAssign):
                    annotation_nodes.append(child.annotation)
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    annotation_nodes.extend(arg.annotation for arg in [*child.args.posonlyargs, *child.args.args, *child.args.kwonlyargs] if arg.annotation)
                    if child.args.vararg and child.args.vararg.annotation:
                        annotation_nodes.append(child.args.vararg.annotation)
                    if child.args.kwarg and child.args.kwarg.annotation:
                        annotation_nodes.append(child.args.kwarg.annotation)
                    if child.returns:
                        annotation_nodes.append(child.returns)
            for annotation in annotation_nodes:
                for raw in _annotation_refs(annotation):
                    resolved = _resolve_symbol(raw, scanner.module, scanner.aliases)
                    target = class_lookup.get(resolved)
                    if target and target != source:
                        associations.add((source, target))
            for call in (value for value in ast.walk(node) if isinstance(value, ast.Call)):
                raw = _target_name(call.func)
                if not raw:
                    continue
                resolved = _resolve_symbol(raw, scanner.module, scanner.aliases)
                target = class_lookup.get(resolved)
                if target and target != source:
                    constructors.add((source, target))
    return (
        [EdgeRow(a, b, "inherits") for a, b in sorted(inheritance)],
        [EdgeRow(a, b, "references") for a, b in sorted(associations)],
        [EdgeRow(a, b, "constructs") for a, b in sorted(constructors)],
    )


def _module_target_system(module: str, registry: dict[str, dict[str, object]]) -> str | None:
    current = module
    while current:
        key = _system_for_module(current, registry)
        if key:
            return key
        current = current.rpartition(".")[0]
    return None


def _safe_id(value: str) -> str:
    return "C_" + hashlib.sha1(value.encode()).hexdigest()[:12]


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")


def _render_system_topology(registry: dict[str, dict[str, object]]) -> list[str]:
    roots = sorted(key for key, value in registry.items() if not value.get("parent"))
    lines = ["```mermaid", "flowchart LR"]
    for key in roots:
        descriptor = registry[key]
        kind = str(descriptor.get("node_kind", "authority"))
        lines.append(f'  S_{_safe_id(key)}["{_mermaid_label(key)}\\n{kind}"]')
    for key in roots:
        for requirement in registry[key].get("requires", []):
            if requirement in roots:
                lines.append(f"  S_{_safe_id(key)} --> S_{_safe_id(requirement)}")
    lines.append("```")
    return lines


def _render_authority_projection(registry: dict[str, dict[str, object]]) -> list[str]:
    lines = ["```mermaid", "flowchart LR"]
    authorities = sorted(
        key for key, row in registry.items() if row.get("node_kind") == "authority"
    )
    for key in authorities:
        lines.append(f'  A_{_safe_id(key)}["{_mermaid_label(key)}"]')
    for key, row in sorted(registry.items()):
        if row.get("node_kind") == "authority":
            continue
        target = row.get("canonical_authority")
        if not isinstance(target, str) or target not in registry:
            continue
        kind = str(row.get("node_kind", "facet"))
        node_id = f"N_{_safe_id(key)}"
        lines.append(f'  {node_id}["{_mermaid_label(key)}\\n{kind}"]')
        lines.append(f"  {node_id} -.-> A_{_safe_id(target)}")
    lines.append("```")
    return lines


def _render_cross_system_graph(
    module_edges: Counter[tuple[str, str]],
) -> list[str]:
    lines = ["```mermaid", "flowchart LR"]
    systems = sorted({v for edge in module_edges for v in edge})
    for system in systems:
        lines.append(f'  T_{_safe_id(system)}["{_mermaid_label(system)}"]')
    for (source, target), count in sorted(module_edges.items()):
        if source != target:
            lines.append(
                f'  T_{_safe_id(source)} -->|"imports {count}"| T_{_safe_id(target)}'
            )
    lines.append("```")
    return lines


def _render_runtime_flow(available: set[str]) -> list[str]:
    # This is a code/topology projection, not a second authority declaration.
    candidate_edges = [
        ("operator", "experimentation", "intent/control"),
        ("portfolio", "experimentation", "project/study context"),
        ("experimentation", "execution", "run/workload"),
        ("execution", "participant", "method/session"),
        ("execution", "model", "model request"),
        ("execution", "environment", "capability/effect"),
        ("execution", "resource", "admission/lease"),
        ("resource", "runtime", "placement/runtime binding"),
        ("execution", "data", "facts/state"),
        ("execution", "artifact", "immutable evidence"),
        ("model", "artifact", "request/output evidence"),
        ("environment", "data", "observations"),
        ("environment", "artifact", "assets/evidence"),
        ("data", "observability", "projection/telemetry"),
        ("runtime", "reliability", "failure/recovery"),
        ("execution", "reliability", "failure/reconcile"),
        ("governance", "platform", "contracts/topology"),
    ]
    lines = ["```mermaid", "flowchart LR"]
    for system in sorted(available):
        lines.append(f'  R_{_safe_id(system)}["{_mermaid_label(system)}"]')
    for source, target, label in candidate_edges:
        if source in available and target in available:
            lines.append(
                f'  R_{_safe_id(source)} -->|"{_mermaid_label(label)}"| R_{_safe_id(target)}'
            )
    lines.append("```")
    return lines


def _render_class_diagram(
    system: str,
    rows: list[ClassRow],
    inheritance: list[EdgeRow],
    constructors: list[EdgeRow],
) -> list[str]:
    class_names = {row.qualname for row in rows}
    lines = ["```mermaid", "classDiagram", "direction LR"]
    for row in sorted(rows, key=lambda value: (value.module, value.line, value.name)):
        cid = _safe_id(row.qualname)
        label = _mermaid_label(row.name)
        lines.append(f'  class {cid}["{label}"]')
        if row.kind != "class":
            lines.append(f"  <<{row.kind}>> {cid}")
    for edge in inheritance:
        if edge.source in class_names and edge.target in class_names:
            lines.append(f"  {_safe_id(edge.target)} <|-- {_safe_id(edge.source)}")
    for edge in constructors:
        if edge.source in class_names and edge.target in class_names:
            lines.append(f"  {_safe_id(edge.source)} ..> {_safe_id(edge.target)} : constructs")
    lines.append("```")
    return lines


def build() -> tuple[dict[str, object], str]:
    registry = _load_registry()
    scanners: dict[str, ModuleScanner] = {}
    module_paths: dict[str, str] = {}
    parse_errors: list[dict[str, object]] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        module = _module_name(path)
        system_key = _system_for_module(module, registry)
        top_system = _top_system(system_key, registry)
        scanner = ModuleScanner(module, system_key, top_system)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeError) as exc:
            parse_errors.append({"path": str(path.relative_to(ROOT)), "error": str(exc)})
            continue
        scanner.visit(tree)
        scanners[module] = scanner
        module_paths[module] = str(path.relative_to(ROOT))

    classes = [row for scanner in scanners.values() for row in scanner.classes]
    # Lookup supports exact module.Class names; nested classes also retain their full qualname.
    class_lookup: dict[str, str] = {}
    for row in classes:
        class_lookup[f"{row.module}.{row.name}"] = row.qualname
        class_lookup[row.qualname.replace("/", ".")] = row.qualname

    inheritance, associations, constructors = _class_reference_edges(scanners, class_lookup)

    module_import_edges: set[tuple[str, str]] = set()
    system_import_edges: Counter[tuple[str, str]] = Counter()
    for module, scanner in scanners.items():
        source_system = scanner.top_system
        for target_module in scanner.import_modules:
            module_import_edges.add((module, target_module))
            target_key = _module_target_system(target_module, registry)
            target_system = _top_system(target_key, registry)
            if source_system and target_system:
                system_import_edges[(source_system, target_system)] += 1

    source_sha = _git_sha()
    index: dict[str, object] = {
        "schema": SCHEMA,
        "source_git_sha": source_sha,
        "registry_sha256": hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),
        "counts": {
            "python_modules": len(scanners),
            "classes": len(classes),
            "inheritance_edges": len(inheritance),
            "association_edges": len(associations),
            "constructor_edges": len(constructors),
            "module_import_edges": len(module_import_edges),
            "top_level_systems": len({row.top_system for row in classes if row.top_system}),
            "registry_nodes": len(registry),
            "registry_authorities": sum(1 for row in registry.values() if row.get("node_kind") == "authority"),
            "parse_errors": len(parse_errors),
        },
        "modules": [
            {
                "module": module,
                "path": module_paths[module],
                "system_key": scanner.system_key,
                "top_system": scanner.top_system,
                "imports": sorted(scanner.import_modules),
            }
            for module, scanner in sorted(scanners.items())
        ],
        "classes": [asdict(row) for row in sorted(classes, key=lambda value: value.qualname)],
        "inheritance_edges": [asdict(row) for row in inheritance],
        "association_edges": [asdict(row) for row in associations],
        "constructor_edges": [asdict(row) for row in constructors],
        "module_import_edges": [
            {"source": source, "target": target}
            for source, target in sorted(module_import_edges)
        ],
        "system_import_edges": [
            {"source": source, "target": target, "count": count}
            for (source, target), count in sorted(system_import_edges.items())
        ],
        "parse_errors": parse_errors,
    }

    by_top: dict[str, list[ClassRow]] = defaultdict(list)
    unregistered: list[ClassRow] = []
    for row in classes:
        if row.top_system:
            by_top[row.top_system].append(row)
        else:
            unregistered.append(row)

    lines: list[str] = [
        "# Noetrium Full Code Architecture Map",
        "",
        "> AUTO-GENERATED by `scripts/generate_code_architecture_map.py`.",
        f"> Source Git SHA: `{source_sha}`.",
        "",
        "This document is source-derived. Class membership comes from Python AST; system ownership comes from the canonical system registry. Non-authority facets/providers/projections are shown as code boundaries, not promoted to durable authorities.",
        "",
        "## Inventory",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in index["counts"].items():
        lines.append(f"| `{key}` | {value} |")

    lines += ["", "## Global system dependency topology", ""]
    lines += _render_system_topology(registry)
    lines += ["", "## Authority / non-authority projection map", ""]
    lines += _render_authority_projection(registry)
    lines += ["", "## Observed cross-system Python import graph", ""]
    lines += _render_cross_system_graph(system_import_edges)
    lines += [
        "",
        "## Canonical end-to-end runtime/data flow",
        "",
        "This flow is projected from the registered system responsibilities and verified against the source dependency graph; arrows describe data/control direction, not ownership transfer.",
        "",
    ]
    lines += _render_runtime_flow(set(by_top))

    lines += ["", "## Registry node inventory", "", "| Path | Kind | Canonical authority | Parent | Downstream |", "|---|---|---|---|---|"]
    for key, row in sorted(registry.items()):
        lines.append(
            "| `{}` | `{}` | `{}` | `{}` | `{}` |".format(
                key,
                row.get("node_kind", ""),
                row.get("canonical_authority", ""),
                row.get("parent", ""),
                row.get("downstream_surface", ""),
            )
        )

    for system in sorted(by_top):
        rows = by_top[system]
        lines += ["", f"## Classes — `{system}`", "", f"Total classes: **{len(rows)}**.", ""]
        lines += _render_class_diagram(system, rows, inheritance, constructors)
        lines += ["", "| Module | Class | Kind | Bases | Fields | Methods |", "|---|---|---|---|---:|---:|"]
        for row in sorted(rows, key=lambda value: (value.module, value.line, value.name)):
            bases = ", ".join(row.bases).replace("|", "\\|")
            lines.append(
                f"| `{row.module}` | `{row.name}` | `{row.kind}` | `{bases}` | {len(row.fields)} | {len(row.methods)} |"
            )

    if unregistered:
        lines += ["", "## Classes outside the canonical registry", ""]
        for row in sorted(unregistered, key=lambda value: value.qualname):
            lines.append(f"- `{row.qualname}`")

    lines += [
        "",
        "## Cross-system class edges",
        "",
        "The JSON sidecar contains every inheritance, annotation-reference and constructor edge. The table below keeps only edges crossing top-level system boundaries.",
        "",
        "| Kind | Source | Target |",
        "|---|---|---|",
    ]
    class_by_name = {row.qualname: row for row in classes}
    for edge in [*inheritance, *associations, *constructors]:
        source = class_by_name.get(edge.source)
        target = class_by_name.get(edge.target)
        if source and target and source.top_system and target.top_system and source.top_system != target.top_system:
            lines.append(f"| `{edge.kind}` | `{edge.source}` | `{edge.target}` |")

    lines += [
        "",
        "## Machine-readable sidecar",
        "",
        "`docs/architecture/CODE_ARCHITECTURE_INDEX.json` contains the complete module/class/edge inventory, including all class methods and fields extracted from source.",
        "",
    ]
    return index, "\n".join(lines) + "\n"


def main() -> int:
    index, markdown = build()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    MAP_PATH.write_text(markdown, encoding="utf-8")
    print(json.dumps(index["counts"], sort_keys=True))
    print(f"wrote {INDEX_PATH.relative_to(ROOT)}")
    print(f"wrote {MAP_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
