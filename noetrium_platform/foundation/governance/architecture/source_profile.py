from __future__ import annotations

"""Single-pass source profiling for repository-wide architecture audits.

The architecture report needs several whole-repository views over the same
Python sources: imports, hotspot metrics, optimization signals, seam edges and
protected-authority calls.  Running those as independent AST scans multiplies
parse cost, while retaining every AST for the entire report multiplies memory.
This module parses each production Python source once, emits compact immutable
facts, and releases the AST immediately.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort

from .hotspots import ModuleHotspot
from .import_graph import ImportEdge, _module_in_roots, _resolve_relative, module_name
from .optimization import (
    IO_NAMES,
    LOCK_NAMES,
    SER_NAMES,
    ModuleOptimizationProfile,
    _called_name,
    _self_mutation,
)
from .seam_graphs import SeamEdge, _call_name, _kw, _literal_str, _literal_string_collection
from .source_authority_contracts import SourceAuthorityRule, SourceAuthorityViolation
from .source_authority_engine import is_production_python


@dataclass(frozen=True, slots=True)
class SourceImportFact:
    path: str
    imports: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ArchitectureSourceProfile:
    import_edges: tuple[ImportEdge, ...]
    import_facts: tuple[SourceImportFact, ...]
    hotspots: tuple[ModuleHotspot, ...]
    optimization_risks: tuple[ModuleOptimizationProfile, ...]
    seam_edges: tuple[SeamEdge, ...]
    authority_violations: tuple[SourceAuthorityViolation, ...]
    parsed_files: int


@dataclass(frozen=True, slots=True)
class _OptimizationRaw:
    module: str
    path: str
    io_sites: int
    serialization_sites: int
    lock_sites: int
    self_mutation_sites: int
    exception_handlers: int
    long_functions: int


def _scan_seams(root: Path, path: Path, tree: ast.AST, nodes: tuple[ast.AST, ...]) -> list[SeamEdge]:
    module = module_name(root, path)
    rel = path.relative_to(root).as_posix()
    out: list[SeamEdge] = []
    for node in getattr(tree, "body", ()):
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value = node.value
        relation = {"EMITTED_EVENT_TYPES": "emits", "CONSUMED_EVENT_TYPES": "consumes"}.get(target_name or "")
        if relation is not None:
            for seam in _literal_string_collection(value):
                out.append(SeamEdge("event", seam, module, relation, rel, node.lineno))

    for node in nodes:
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "CapabilityDescriptor":
                seam = _literal_str(_kw(node, "capability_id")) or (_literal_str(node.args[0]) if node.args else None)
                if seam:
                    out.append(SeamEdge("capability", seam, module, "provides", rel, node.lineno))
            elif name == "CapabilityRequest":
                seam = _literal_str(_kw(node, "capability_id")) or (_literal_str(node.args[0]) if node.args else None)
                if seam:
                    out.append(SeamEdge("capability", seam, module, "consumes", rel, node.lineno))
            elif name == "describe" and node.args:
                seam = _literal_str(node.args[0])
                if seam:
                    out.append(SeamEdge("capability", seam, module, "consumes", rel, node.lineno))
            elif name == "dispatch":
                seam = _literal_str(_kw(node, "operation_type"))
                if seam:
                    out.append(SeamEdge("operation", seam, module, "emits", rel, node.lineno))
            elif name == "EventEnvelope":
                seam = _literal_str(_kw(node, "event_type"))
                if seam:
                    out.append(SeamEdge("event", seam, module, "emits", rel, node.lineno))
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.In)):
            left = node.left
            if isinstance(left, ast.Attribute) and left.attr == "event_type":
                for comparator in node.comparators:
                    seam = _literal_str(comparator)
                    if seam:
                        out.append(SeamEdge("event", seam, module, "consumes", rel, node.lineno))
    return out


def scan_architecture_source_profile(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort,
    package_roots: tuple[str, ...] = ("noetrium_platform", "components", "orchestration", "noetrium", "projects"),
    authority_rules: Iterable[SourceAuthorityRule] = (),
) -> ArchitectureSourceProfile:
    """Parse each production Python file once and emit compact audit facts.

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: N is total Python source plus AST nodes; directory files, AST nodes, import aliases and seam operands are each visited once, while authority rules are a fixed policy set independent of repository size.
    """

    root = Path(root).resolve()
    rules = tuple(authority_rules)
    edges: list[ImportEdge] = []
    import_facts: list[SourceImportFact] = []
    hotspot_rows: list[ModuleHotspot] = []
    optimization_raw: list[_OptimizationRaw] = []
    seam_rows: list[SeamEdge] = []
    authority_rows: list[SourceAuthorityViolation] = []
    parsed = 0

    python_sources = tuple(
        blob
        for blob in source_index.documents(suffixes={".py"})
        if any(
            blob.relative_path == prefix or blob.relative_path.startswith(prefix + "/")
            for prefix in package_roots
        )
    )
    for source in python_sources:
        path = root / source.relative_path
        text = source.text
        tree = source_index.python_tree(source.relative_path, sha256=source.sha256)
        parsed += 1
        nodes = tuple(ast.walk(tree))
        module = module_name(root, path)
        rel = source.relative_path

        raw_imports: list[tuple[str, int]] = []
        aliases: dict[str, str] = {}
        for node in nodes:
            if isinstance(node, ast.Import):
                raw_imports.extend((alias.name, node.lineno) for alias in node.names)
                for alias in node.names:
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name
                    target_name = alias.name
                    if _module_in_roots(target_name, package_roots):
                        edges.append(ImportEdge(module, target_name, rel, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                raw_imports.append((node.module or "", node.lineno))
                if node.module:
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                target = (
                    _resolve_relative(
                        module,
                        node.level,
                        node.module,
                        source_is_package=path.name == "__init__.py",
                    )
                    if node.level
                    else (node.module or "")
                )
                if _module_in_roots(target, package_roots):
                    edges.append(ImportEdge(module, target, rel, node.lineno))
        import_facts.append(SourceImportFact(rel, tuple(raw_imports)))

        funcs = tuple(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        branches = sum(isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.Match, ast.IfExp)) for n in nodes)
        imports_count = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in nodes)
        classes = sum(isinstance(n, ast.ClassDef) for n in nodes)
        handlers = sum(isinstance(n, ast.ExceptHandler) for n in nodes)
        max_fn = max((getattr(n, "end_lineno", n.lineno) - n.lineno + 1 for n in funcs), default=0)
        lines = len(text.splitlines())
        hotspot_score = lines + branches * 8 + imports_count * 3 + handlers * 10 + max(0, max_fn - 50) * 2
        hotspot_rows.append(ModuleHotspot(
            module, rel, lines, len(funcs), classes, imports_count, branches, handlers, max_fn, hotspot_score,
        ))

        calls = tuple(n for n in nodes if isinstance(n, ast.Call))
        io = sum((_called_name(n) in IO_NAMES) for n in calls)
        ser = sum((_called_name(n) in SER_NAMES) for n in calls)
        lock = sum((_called_name(n) in LOCK_NAMES) for n in calls)
        muts = sum(_self_mutation(n) for n in nodes)
        long_functions = sum((getattr(n, "end_lineno", n.lineno) - n.lineno + 1) > 50 for n in funcs)
        optimization_raw.append(_OptimizationRaw(module, rel, io, ser, lock, muts, handlers, long_functions))

        seam_rows.extend(_scan_seams(root, path, tree, nodes))

        if rules and is_production_python(root, path):
            for node in calls:
                for rule in rules:
                    if rule.matches(node, aliases) and module not in rule.allowed_modules:
                        authority_rows.append(SourceAuthorityViolation(
                            authority=rule.authority,
                            primitive=rule.primitive,
                            module=module,
                            path=rel,
                            line=node.lineno,
                            allowed_modules=rule.allowed_modules,
                            detail=(
                                f"{rule.primitive} is a protected mutation primitive; "
                                f"authority belongs to {', '.join(rule.allowed_modules)}"
                            ),
                        ))

        # The shared source index owns the AST for this cut; this scanner retains only compact facts.
        del nodes, tree, text

    fan_in: dict[str, int] = {}
    fan_out: dict[str, int] = {}
    for edge in edges:
        fan_out[edge.source_module] = fan_out.get(edge.source_module, 0) + 1
        fan_in[edge.target_module] = fan_in.get(edge.target_module, 0) + 1

    optimization_rows: list[ModuleOptimizationProfile] = []
    for row in optimization_raw:
        fi = fan_in.get(row.module, 0)
        fo = fan_out.get(row.module, 0)
        score = (
            fi * 4 + fo * 3 + row.io_sites * 8 + row.serialization_sites * 4
            + row.lock_sites * 12 + row.self_mutation_sites * 5
            + row.exception_handlers * 8 + row.long_functions * 20
        )
        reasons: list[str] = []
        if fi >= 8:
            reasons.append("HIGH_FAN_IN")
        if fo >= 10:
            reasons.append("HIGH_FAN_OUT")
        if row.io_sites >= 6:
            reasons.append("IO_CONCENTRATION")
        if row.serialization_sites >= 8:
            reasons.append("SERIALIZATION_CONCENTRATION")
        if row.lock_sites >= 3:
            reasons.append("LOCK_CONTENTION_RISK")
        if row.self_mutation_sites >= 8:
            reasons.append("STATE_MUTATION_CONCENTRATION")
        if row.exception_handlers >= 4:
            reasons.append("FAILURE_BRANCH_CONCENTRATION")
        if row.long_functions:
            reasons.append("LONG_FUNCTION")
        optimization_rows.append(ModuleOptimizationProfile(
            row.module, row.path, fi, fo, row.io_sites, row.serialization_sites,
            row.lock_sites, row.self_mutation_sites, row.exception_handlers,
            row.long_functions, score, tuple(reasons),
        ))

    unique_seams = {
        (edge.kind, edge.seam_id, edge.module, edge.relation, edge.path, edge.line): edge
        for edge in seam_rows
    }
    seam_edges = tuple(
        sorted(unique_seams.values(), key=lambda x: (x.kind, x.seam_id, x.relation, x.module, x.line))
    )

    return ArchitectureSourceProfile(
        import_edges=tuple(edges),
        import_facts=tuple(import_facts),
        hotspots=tuple(sorted(hotspot_rows, key=lambda x: (-x.score, x.module))),
        optimization_risks=tuple(sorted(optimization_rows, key=lambda x: (-x.risk_score, x.module))),
        seam_edges=seam_edges,
        authority_violations=tuple(authority_rows),
        parsed_files=parsed,
    )


__all__ = ["ArchitectureSourceProfile", "SourceImportFact", "scan_architecture_source_profile"]
