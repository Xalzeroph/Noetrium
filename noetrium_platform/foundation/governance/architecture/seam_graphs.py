from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .import_graph import module_name
from .source_index import source_nodes, source_tree


@dataclass(frozen=True, slots=True)
class SeamEdge:
    kind: str
    seam_id: str
    module: str
    relation: str
    path: str
    line: int


def _literal_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _kw(node: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in node.keywords if item.arg == name), None)


def _literal_string_collection(node: ast.AST | None) -> tuple[str, ...]:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return ()
    rows=[]
    for item in node.elts:
        value=_literal_str(item)
        if value is None:
            return ()
        rows.append(value)
    return tuple(rows)


def _scan_file(root: Path, path: Path) -> tuple[SeamEdge, ...]:
    module = module_name(root, path)
    rel = path.relative_to(root).as_posix()
    tree = source_tree(path)
    out: list[SeamEdge] = []
    for node in tree.body:
        target_name=None; value=None
        if isinstance(node, ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0], ast.Name):
            target_name=node.targets[0].id; value=node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name=node.target.id; value=node.value
        relation={"EMITTED_EVENT_TYPES":"emits","CONSUMED_EVENT_TYPES":"consumes"}.get(target_name or "")
        if relation is not None:
            for seam in _literal_string_collection(value):
                out.append(SeamEdge("event",seam,module,relation,rel,node.lineno))
    for node in source_nodes(path):
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
    return tuple(out)


def scan_seam_graphs(root: Path) -> tuple[SeamEdge, ...]:
    edges: list[SeamEdge] = []
    for prefix in ("noetrium_platform", "projects"):
        package = root / prefix
        if not package.exists():
            continue
        for path in sorted(package.rglob("*.py")):
            edges.extend(_scan_file(root, path))
    unique={(edge.kind,edge.seam_id,edge.module,edge.relation,edge.path,edge.line):edge for edge in edges}
    return tuple(sorted(unique.values(), key=lambda x: (x.kind, x.seam_id, x.relation, x.module, x.line)))


def declared_capability_graph(audit) -> tuple[SeamEdge, ...]:
    rows: list[SeamEdge] = []
    for descriptor in audit.descriptors:
        for capability in descriptor.provides:
            rows.append(SeamEdge("capability", capability, descriptor.component_id, "provides", "<declared-component-registry>", 0))
        for capability in descriptor.requires:
            rows.append(SeamEdge("capability", capability, descriptor.component_id, "consumes", "<declared-component-registry>", 0))
    return tuple(rows)


def partition_seam_graphs(edges: tuple[SeamEdge, ...], *, declared_capabilities: tuple[SeamEdge, ...] = ()):
    capability = tuple(sorted(
        tuple(x for x in edges if x.kind == "capability") + declared_capabilities,
        key=lambda x: (x.seam_id, x.relation, x.module, x.line),
    ))
    operation = tuple(x for x in edges if x.kind == "operation")
    event = tuple(x for x in edges if x.kind == "event")
    return capability, operation, event


__all__ = ["SeamEdge", "declared_capability_graph", "partition_seam_graphs", "scan_seam_graphs"]
