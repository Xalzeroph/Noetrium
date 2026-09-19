#!/usr/bin/env python3
"""Generate a whole-repository code architecture map.

This complements ``generate_code_architecture_map.py``. The core generator owns
fine-grained ``noetrium_platform`` system/class diagrams; this generator scans
all currently materialized tracked Python plus TypeScript/JavaScript source and
projects it into repository roles (facade, core, reference, reproductions,
tooling, SDK, tests).

The generator deliberately tolerates files staged for deletion by another
canonical generator in the same transaction. ``git ls-files`` continues to
report those paths until the transaction is committed; treating the index as if
it were the working tree made architecture regeneration order-dependent.
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
INDEX_PATH = ROOT / "docs/architecture/REPOSITORY_CODE_ARCHITECTURE_INDEX.json"
MAP_PATH = ROOT / "docs/architecture/REPOSITORY_CODE_ARCHITECTURE_MAP.md"
SCHEMA = "noetrium-repository-code-architecture-index.v1"

ROLE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("noetrium_platform/", "core_platform"),
    ("noetrium/", "public_facade"),
    ("components/", "reference_components"),
    ("orchestration/", "reference_orchestration"),
    ("research/", "research_reproductions"),
    ("scripts/", "tooling"),
    ("sdk/", "sdk"),
    ("examples/", "examples"),
    ("tests/", "tests"),
)
INTERNAL_MODULE_ROOTS = {
    "noetrium_platform",
    "noetrium",
    "components",
    "orchestration",
    "research",
    "scripts",
    "tests",
}


def _git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _tracked_files() -> tuple[Path, ...]:
    """Return tracked paths that still exist in the current working tree.

    Generated-surface migrations can delete tracked files before the enclosing
    transaction is committed. ``git ls-files`` still lists those index entries;
    source analysis must model the materialized tree, not stale index entries.
    """

    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    values = [Path(part.decode()) for part in raw.split(b"\0") if part]
    return tuple(path for path in values if (ROOT / path).is_file())


def _role(path: Path) -> str:
    raw = path.as_posix()
    for prefix, role in ROLE_PREFIXES:
        if raw.startswith(prefix):
            return role
    return "other"


def _module(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _expr(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return node.__class__.__name__


def _safe_id(text: str) -> str:
    return "N_" + hashlib.sha1(text.encode()).hexdigest()[:12]


def _label(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', "'").replace("\n", " ")


@dataclass(frozen=True, slots=True)
class SymbolRow:
    language: str
    role: str
    path: str
    module: str
    qualname: str
    name: str
    kind: str
    bases: tuple[str, ...]
    decorators: tuple[str, ...]
    fields: tuple[str, ...]
    methods: tuple[str, ...]
    line: int


@dataclass(frozen=True, slots=True)
class ImportEdge:
    source_module: str
    source_role: str
    target_module: str
    target_role: str


class PythonScanner(ast.NodeVisitor):
    def __init__(self, path: Path, role: str, module: str) -> None:
        self.path = path
        self.role = role
        self.module = module
        self.scope: list[str] = []
        self.symbols: list[SymbolRow] = []
        self.imports: set[str] = set()

    def _qualname(self, name: str) -> str:
        return ".".join((self.module, *self.scope, name))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".", 1)[0] in INTERNAL_MODULE_ROOTS:
                self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.level == 0 and node.module.split(".", 1)[0] in INTERNAL_MODULE_ROOTS:
            self.imports.add(node.module)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = tuple(_expr(base) for base in node.bases)
        base_names = {base.rsplit(".", 1)[-1] for base in bases}
        decorators = tuple(_expr(value) for value in node.decorator_list)
        if "Protocol" in base_names:
            kind = "protocol"
        elif "StrEnum" in base_names or "Enum" in base_names or "IntEnum" in base_names:
            kind = "enum"
        elif any(value.startswith("dataclass") for value in decorators):
            kind = "dataclass"
        elif "ABC" in base_names:
            kind = "abstract_class"
        else:
            kind = "class"
        fields: list[str] = []
        methods: list[str] = []
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fields.append(f"{child.target.id}: {_expr(child.annotation)}")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(child.name)
            elif isinstance(child, ast.Assign) and kind == "enum":
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        fields.append(target.id)
        self.symbols.append(SymbolRow(
            language="python",
            role=self.role,
            path=self.path.as_posix(),
            module=self.module,
            qualname=self._qualname(node.name),
            name=node.name,
            kind=kind,
            bases=bases,
            decorators=decorators,
            fields=tuple(fields),
            methods=tuple(methods),
            line=node.lineno,
        ))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _target_role(module: str) -> str:
    prefix = module.split(".", 1)[0]
    mapping = {
        "noetrium_platform": "core_platform",
        "noetrium": "public_facade",
        "components": "reference_components",
        "orchestration": "reference_orchestration",
        "research": "research_reproductions",
        "scripts": "tooling",
        "tests": "tests",
    }
    return mapping.get(prefix, "external")


def _script_symbols(path: Path, role: str) -> list[SymbolRow]:
    """Extract top-level TS/JS class/interface/enum/type declarations conservatively."""

    text = (ROOT / path).read_text(encoding="utf-8-sig", errors="replace")
    pattern = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:declare\s+)?(class|interface|enum|type)\s+([A-Za-z_$][\w$]*)"
    )
    language = "typescript" if path.suffix.lower() in {".ts", ".tsx"} else "javascript"
    rows: list[SymbolRow] = []
    for match in pattern.finditer(text):
        kind_raw, name = match.groups()
        kind = {"interface": "protocol", "enum": "enum", "type": "type_alias"}.get(kind_raw, "class")
        line = text.count("\n", 0, match.start()) + 1
        rows.append(SymbolRow(
            language=language,
            role=role,
            path=path.as_posix(),
            module=path.as_posix(),
            qualname=f"{path.as_posix()}::{name}",
            name=name,
            kind=kind,
            bases=(),
            decorators=(),
            fields=(),
            methods=(),
            line=line,
        ))
    return rows


def _repository_layer_flow() -> list[str]:
    return [
        "```mermaid",
        "flowchart LR",
        '  U["downstream paper / user"]',
        '  F["noetrium public facade"]',
        '  C["noetrium_platform core"]',
        '  P["providers / adapters"]',
        '  E["data + artifact evidence"]',
        '  O["observability projections"]',
        '  R["reference components / orchestration"]',
        '  X["research reproductions"]',
        '  S["SDK"]',
        '  T["governance/tooling"]',
        '  Q["tests / assurance"]',
        "  U --> F",
        "  U --> S",
        "  F --> C",
        "  S --> F",
        "  R --> F",
        "  X --> R",
        "  X --> F",
        "  C --> P",
        "  C --> E",
        "  E --> O",
        "  T -. audits/generates .-> C",
        "  Q -. verifies .-> F",
        "  Q -. verifies .-> C",
        "  Q -. verifies .-> R",
        "```",
    ]


def _class_diagram(role: str, rows: list[SymbolRow], *, max_nodes: int = 600) -> list[str]:
    lines = ["```mermaid", "classDiagram", "direction LR"]
    selected = rows[:max_nodes]
    for row in selected:
        cid = _safe_id(row.qualname)
        lines.append(f'  class {cid}["{_label(row.name)}"]')
        stereotype = row.kind.replace("abstract_class", "abstract")
        if stereotype not in {"class", "dataclass"}:
            lines.append(f"  <<{stereotype}>> {cid}")
        elif row.kind == "dataclass":
            lines.append(f"  <<dataclass>> {cid}")
    lines.append("```")
    if len(rows) > max_nodes:
        lines.append(f"\n> Mermaid renderer safety cap: showing {max_nodes}/{len(rows)} nodes here. Every symbol remains listed in the table and JSON sidecar.\n")
    return lines


def build() -> tuple[dict[str, object], str]:
    tracked = _tracked_files()
    python_paths = tuple(path for path in tracked if path.suffix == ".py" and ".local" not in path.parts and (ROOT / path).is_file())
    script_paths = tuple(path for path in tracked if path.suffix.lower() in {".ts", ".tsx", ".js", ".mjs", ".cjs"} and "node_modules" not in path.parts and (ROOT / path).is_file())

    symbols: list[SymbolRow] = []
    import_edges: set[ImportEdge] = set()
    parse_errors: list[dict[str, str]] = []
    module_role: dict[str, str] = {}

    for path in python_paths:
        role = _role(path)
        module = _module(path)
        module_role[module] = role
        scanner = PythonScanner(path, role, module)
        try:
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"), filename=path.as_posix())
        except (SyntaxError, UnicodeError) as exc:
            parse_errors.append({"path": path.as_posix(), "error": str(exc)})
            continue
        scanner.visit(tree)
        symbols.extend(scanner.symbols)
        for target in scanner.imports:
            import_edges.add(
                ImportEdge(
                    source_module=module,
                    source_role=role,
                    target_module=target,
                    target_role=_target_role(target),
                )
            )

    for path in script_paths:
        symbols.extend(_script_symbols(path, _role(path)))

    role_counts = Counter(row.role for row in symbols)
    language_counts = Counter(row.language for row in symbols)
    python_module_counts = Counter(module_role.values())
    role_import_counts: Counter[tuple[str, str]] = Counter(
        (edge.source_role, edge.target_role) for edge in import_edges
    )

    index: dict[str, object] = {
        "schema": SCHEMA,
        "source_git_sha": _git_sha(),
        "counts": {
            "tracked_files": len(tracked),
            "python_files": len(python_paths),
            "typescript_javascript_files": len(script_paths),
            "symbols": len(symbols),
            "python_import_edges": len(import_edges),
            "parse_errors": len(parse_errors),
        },
        "role_symbol_counts": dict(sorted(role_counts.items())),
        "language_symbol_counts": dict(sorted(language_counts.items())),
        "role_python_module_counts": dict(sorted(python_module_counts.items())),
        "role_import_counts": [
            {"source_role": source, "target_role": target, "count": count}
            for (source, target), count in sorted(role_import_counts.items())
        ],
        "parse_errors": parse_errors,
        "symbols": [asdict(row) for row in symbols],
        "python_import_edges": [asdict(edge) for edge in sorted(import_edges, key=lambda value: (value.source_module, value.target_module))],
    }

    markdown = [
        "# Noetrium Whole-Repository Code Architecture Map",
        "",
        "> AUTO-GENERATED by `scripts/generate_repository_code_architecture_map.py`.",
        f"> Source Git SHA: `{index['source_git_sha']}`.",
        "",
        "This is the repository-wide companion to `CODE_ARCHITECTURE_MAP.md`. The core platform map provides fine-grained system/authority diagrams for every `noetrium_platform` class; this document adds public facade, reference implementations, reproductions, tooling, SDK and tests.",
        "",
        "## Repository inventory",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in index["counts"].items():
        markdown.append(f"| `{key}` | {value} |")
    markdown.extend(["", "### Symbols by role", "", "| Role | Symbols | Python modules |", "|---|---:|---:|"])
    all_roles = sorted(set(role_counts) | set(python_module_counts))
    for role in all_roles:
        markdown.append(f"| `{role}` | {role_counts.get(role, 0)} | {python_module_counts.get(role, 0)} |")
    markdown.extend(["", "### Symbols by language", "", "| Language | Symbols |", "|---|---:|"])
    for language, count in sorted(language_counts.items()):
        markdown.append(f"| `{language}` | {count} |")
    markdown.extend(["", "## Repository layer/data flow", "", *_repository_layer_flow(), ""])

    markdown.extend(["## Observed cross-role Python dependency graph", "", "```mermaid", "flowchart LR"])
    role_ids = {role: _safe_id(role) for role in sorted(set(role_counts) | {edge.source_role for edge in import_edges} | {edge.target_role for edge in import_edges if edge.target_role != 'external'})}
    for role, rid in role_ids.items():
        markdown.append(f'  {rid}["{_label(role)}"]')
    for (source, target), count in sorted(role_import_counts.items()):
        if target == "external" or source not in role_ids or target not in role_ids:
            continue
        markdown.append(f'  {role_ids[source]} -->|"imports {count}"| {role_ids[target]}')
    markdown.extend(["```", ""])

    markdown.extend([
        "## Core platform detail",
        "",
        "Every `noetrium_platform` class, inheritance edge, annotation association, constructor edge, system import edge and authority projection is expanded in [`CODE_ARCHITECTURE_MAP.md`](./CODE_ARCHITECTURE_MAP.md). Its machine-readable sidecar is [`CODE_ARCHITECTURE_INDEX.json`](./CODE_ARCHITECTURE_INDEX.json).",
        "",
    ])

    by_role: dict[str, list[SymbolRow]] = defaultdict(list)
    for row in symbols:
        by_role[row.role].append(row)
    for role in sorted(by_role):
        rows = sorted(by_role[role], key=lambda row: (row.path, row.line, row.qualname))
        markdown.extend([f"## Repository role — `{role}`", "", f"Total symbols: **{len(rows)}**.", ""])
        if role == "core_platform":
            markdown.extend(["Core class diagrams are intentionally not duplicated here; see `CODE_ARCHITECTURE_MAP.md` for the full 16-system expansion.", ""])
        else:
            markdown.extend(_class_diagram(role, rows))
            markdown.append("")
        markdown.extend([
            "| Language | Path | Symbol | Kind | Bases | Fields | Methods |",
            "|---|---|---|---|---|---:|---:|",
        ])
        for row in rows:
            bases = ", ".join(row.bases).replace("|", "\\|")
            markdown.append(
                f"| `{row.language}` | `{row.path}` | `{row.qualname}` | `{row.kind}` | `{bases}` | {len(row.fields)} | {len(row.methods)} |"
            )
        markdown.append("")

    if parse_errors:
        markdown.extend(["## Parse errors", ""])
        for row in parse_errors:
            markdown.append(f"- `{row['path']}` — {row['error']}")
        markdown.append("")

    return index, "\n".join(markdown).rstrip() + "\n"


def main() -> int:
    index, markdown = build()
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    MAP_PATH.write_text(markdown, encoding="utf-8")
    print(json.dumps(index["counts"], sort_keys=True))
    print(json.dumps(index["role_symbol_counts"], sort_keys=True))
    print(json.dumps(index["language_symbol_counts"], sort_keys=True))
    print(f"wrote {INDEX_PATH.relative_to(ROOT)}")
    print(f"wrote {MAP_PATH.relative_to(ROOT)}")
    return 0 if not index["parse_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
