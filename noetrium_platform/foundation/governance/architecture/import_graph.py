from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from .source_index import cached_import_edges, source_nodes, source_tree


@dataclass(frozen=True, slots=True)
class ImportEdge:
    source_module: str
    target_module: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class ImportRule:
    source_prefix: str
    target_prefix: str
    reason: str


@dataclass(frozen=True, slots=True)
class ImportViolation:
    edge: ImportEdge
    reason: str


@dataclass(frozen=True, slots=True)
class LayerViolation:
    edge: ImportEdge
    source_layer: str
    target_layer: str
    reason: str


def _module_in_roots(module: str, roots: tuple[str, ...]) -> bool:
    """Match package roots on module boundaries, never by raw prefix."""

    return any(module == root or module.startswith(root + ".") for root in roots)


def _prefix_matches(module: str, prefix: str) -> bool:
    """Match an architecture-rule prefix on a Python module boundary."""

    normalized = prefix.rstrip(".")
    return module == normalized or module.startswith(normalized + ".")


def module_name(root: Path, path: Path) -> str:
    rel=path.relative_to(root).with_suffix("")
    parts=list(rel.parts)
    if parts and parts[-1]=="__init__": parts.pop()
    return ".".join(parts)


def _resolve_relative(source: str, level: int, module: str | None, *, source_is_package: bool = False) -> str:
    parts=source.split(".")
    # __init__.py represents a package, while ordinary files represent modules.
    package=parts if source_is_package else parts[:-1]
    if level>0:
        keep=max(0,len(package)-(level-1)); base=package[:keep]
    else: base=[]
    if module: base.extend(module.split("."))
    return ".".join(base)


def scan_imports(root: Path, package_roots: tuple[str, ...] = ("noetrium_platform", "components", "orchestration", "noetrium", "projects")) -> tuple[ImportEdge, ...]:
    cached = cached_import_edges(package_roots)
    if cached is not None:
        return tuple(cached)
    edges=[]
    for prefix in package_roots:
        pkg=root/prefix
        if not pkg.exists(): continue
        for path in sorted(pkg.rglob("*.py")):
            src=module_name(root,path)
            tree=source_tree(path)
            for node in source_nodes(path):
                if isinstance(node,ast.Import):
                    for alias in node.names:
                        if _module_in_roots(alias.name, package_roots): edges.append(ImportEdge(src,alias.name,path.relative_to(root).as_posix(),node.lineno))
                elif isinstance(node,ast.ImportFrom):
                    target=_resolve_relative(src,node.level,node.module,source_is_package=path.name=="__init__.py") if node.level else (node.module or "")
                    if _module_in_roots(target, package_roots): edges.append(ImportEdge(src,target,path.relative_to(root).as_posix(),node.lineno))
    return tuple(edges)


def _is_allowed_downstream_api_edge(edge: ImportEdge) -> bool:
    """Allow stable Noetrium facades to re-export downstream extension APIs."""

    if not edge.source_module.startswith("noetrium."):
        return False
    return edge.target_module == "components.api" or edge.target_module.startswith(
        "components.api."
    ) or edge.target_module == "orchestration.api" or edge.target_module.startswith(
        "orchestration.api."
    )


def audit_import_rules(edges: tuple[ImportEdge,...], rules: tuple[ImportRule,...]) -> tuple[ImportViolation,...]:
    out=[]
    for edge in edges:
        if _is_allowed_downstream_api_edge(edge):
            continue
        for rule in rules:
            if _prefix_matches(edge.source_module, rule.source_prefix) and _prefix_matches(edge.target_module, rule.target_prefix):
                out.append(ImportViolation(edge,rule.reason))
    return tuple(out)


_LAYER_NAMES = frozenset({"api", "runtime", "providers", "composition", "implementations"})
_FORBIDDEN_LAYER_EDGES = frozenset({
    ("api", "runtime"), ("api", "providers"), ("api", "composition"),
    ("runtime", "providers"), ("runtime", "composition"), ("providers", "composition"),
})


def _path_layer(path: Path) -> tuple[tuple[str, ...], str] | None:
    directories = path.parent.parts
    positions = [index for index, part in enumerate(directories) if part in _LAYER_NAMES]
    if not positions:
        return None
    index = positions[-1]
    return directories[:index], directories[index]


def _module_path(root: Path, module: str) -> Path | None:
    candidate = root.joinpath(*module.split("."))
    file_candidate = candidate.with_suffix(".py")
    if file_candidate.is_file():
        return file_candidate
    package_candidate = candidate / "__init__.py"
    return package_candidate if package_candidate.is_file() else None


def audit_layer_dag(root: Path, edges: tuple[ImportEdge, ...] | None = None) -> tuple[LayerViolation, ...]:
    rows: list[LayerViolation] = []
    for edge in edges or scan_imports(root):
        source = _path_layer(root / edge.path)
        target_path = _module_path(root, edge.target_module)
        target = _path_layer(target_path) if target_path is not None else None
        if source is None or target is None:
            continue
        source_prefix, source_layer = source
        target_prefix, target_layer = target
        if source_prefix != target_prefix or (source_layer, target_layer) not in _FORBIDDEN_LAYER_EDGES:
            continue
        rows.append(LayerViolation(
            edge,
            source_layer,
            target_layer,
            f"{source_layer} must depend on the subsystem API, not {target_layer}",
        ))
    return tuple(rows)


def package_cycles(edges: tuple[ImportEdge,...], depth: int=2) -> tuple[tuple[str,...],...]:
    def bucket(name: str) -> str:
        # Platform is a hierarchical root.  Its foundational kernel and composition
        # root intentionally sit on opposite sides of every child system: children
        # depend on kernel primitives, while composition depends on children.  If both
        # are collapsed into the same depth-2 ``noetrium_platform.foundation.kernel`` bucket,
        # every valid parent/child relationship becomes a false cycle.  Keep those two
        # architectural planes distinct while retaining the historical depth argument
        # for all ordinary packages and synthetic tests.
        if depth == 2 and name.startswith("noetrium_platform.foundation.kernel.kernel"):
            return "noetrium_platform.foundation"
        if depth == 2 and name.startswith("noetrium_platform.composition"):
            return "noetrium_platform.composition"
        return ".".join(name.split(".")[:depth])

    graph: dict[str,set[str]]={}
    for e in edges:
        # Aggregate facades intentionally re-export downstream public APIs.
        # Their allowed seam must not be treated as a package cycle when the
        # downstream implementation imports leaf Noe contracts.
        if _is_allowed_downstream_api_edge(e):
            continue
        a,b=bucket(e.source_module),bucket(e.target_module)
        if a!=b: graph.setdefault(a,set()).add(b); graph.setdefault(b,set())
    cycles=set()
    def canonical(cycle:list[str])->tuple[str,...]:
        body=cycle[:-1]; rots=[tuple(body[i:]+body[:i]) for i in range(len(body))]; rev=list(reversed(body)); rots += [tuple(rev[i:]+rev[:i]) for i in range(len(rev))]
        return min(rots)
    for start in sorted(graph):
        stack=[(start,[start])]
        while stack:
            node,path=stack.pop()
            for nxt in graph.get(node,()):
                if nxt==start and len(path)>1: cycles.add(canonical(path+[start]))
                elif nxt not in path and len(path)<len(graph): stack.append((nxt,path+[nxt]))
    return tuple(sorted(cycles))


DEFAULT_IMPORT_RULES=(
    ImportRule("components", "orchestration", "component layer cannot depend upward on orchestration"),
    ImportRule("noetrium", "components", "facade cannot own or import reusable components"),
    ImportRule("noetrium", "orchestration", "facade cannot own or import orchestration"),
    ImportRule("noetrium_platform", "components", "platform cannot depend on downstream components"),
    ImportRule("noetrium_platform", "orchestration", "platform cannot depend on downstream orchestration"),
    ImportRule("orchestration", "components", "orchestration cannot reach into component implementations"),
    ImportRule("noetrium_platform.capabilities.model.request.api","noetrium_platform.capabilities.model.request.runtime","Model Request API cannot depend on its runtime implementation"),
    ImportRule("noetrium_platform.capabilities.model.request.api","noetrium_platform.capabilities.model.request.prompt.runtime","Model Request API cannot depend on Prompt OS implementation"),
    ImportRule("noetrium_platform.research.execution.capability.api","noetrium_platform.research.execution.capability.runtime","Capability API cannot depend on capability runtime implementation"),
    ImportRule("noetrium_platform.evidence.data.projection.api","noetrium_platform.evidence.data.projection.runtime","Projection API cannot depend on projection runtime implementation"),
    ImportRule("noetrium_platform.evidence.data.fact.api","noetrium_platform.evidence.data.fact.runtime","Fact API cannot depend on fact runtime implementation"),
    ImportRule("noetrium_platform.capabilities.participant.capability.api","noetrium_platform.research.execution.capability.runtime","Participant capability API cannot depend on execution capability runtime implementation"),
    ImportRule("noetrium_platform.evidence.data.record.api","noetrium_platform.evidence.data.fact.api","Record-plane API cannot depend upward on durable-fact API"),
    ImportRule("noetrium_platform.evidence.data.record.api","noetrium_platform.evidence.observability.api","Record-plane API cannot depend upward on observability API"),
    ImportRule("noetrium_platform.evidence.data.record.api","noetrium_platform.capabilities.participant.capability.api","Record-plane API cannot depend upward on capability API"),
    ImportRule("noetrium_platform","projects","generic platform must not import a concrete project/application"),
    ImportRule("noetrium_platform.capabilities.participant.method.api","noetrium_platform.capabilities.model.serving","Method ABI cannot depend on model-serving implementation"),
    ImportRule("noetrium_platform.capabilities.participant.method.api","noetrium_platform.capabilities.model.request.prompt.runtime","Method ABI cannot depend on Prompt OS implementation"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.service.runtime","noetrium_platform.research.execution.runtime.manager","Service OS cannot depend upward on Runtime Manager"),
    ImportRule("noetrium_platform.infrastructure.reliability.primitives","noetrium_platform.research.execution.runtime.manager","Reliability contracts cannot depend on Runtime Manager"),
    ImportRule("noetrium_platform.infrastructure.reliability.primitives","noetrium_platform.infrastructure.lifecycle.service.runtime","Reliability contracts cannot depend on Service OS"),
    ImportRule("noetrium_platform.research.experimentation.study","noetrium_platform.capabilities.participant.definition.runtime","Study execution cannot import participant definition factories"),
    ImportRule("noetrium_platform.research.experimentation.study","noetrium_platform.capabilities.participant.binding.runtime","Study execution cannot import participant binding runtime"),
    ImportRule("noetrium_platform.research.experimentation.study","noetrium_platform.capabilities.participant.session.runtime","Study execution cannot import participant session runtime"),
    ImportRule("noetrium_platform.research.execution.workflow.implementations","noetrium_platform.capabilities.participant.definition.runtime","Workflow execution cannot import participant definition factories"),
    ImportRule("noetrium_platform.research.execution.workflow.implementations","noetrium_platform.capabilities.participant.binding.runtime","Workflow execution cannot import participant binding runtime"),
    ImportRule("noetrium_platform.research.execution.workflow.implementations","noetrium_platform.capabilities.participant.session.runtime","Workflow execution cannot import participant session runtime"),
    ImportRule("noetrium_platform.research.execution.runtime.manager","noetrium_platform.capabilities.participant.definition.runtime","Runtime Manager cannot import participant definition runtime"),
    ImportRule("noetrium_platform.research.execution.runtime.manager","noetrium_platform.capabilities.participant.binding.runtime","Runtime Manager cannot import participant binding runtime"),
    ImportRule("noetrium_platform.research.execution.runtime.manager","noetrium_platform.capabilities.participant.session.runtime","Runtime Manager cannot import participant session runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.service.runtime","noetrium_platform.capabilities.participant.definition.runtime","Service OS cannot import participant definition runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.service.runtime","noetrium_platform.capabilities.participant.binding.runtime","Service OS cannot import participant binding runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.service.runtime","noetrium_platform.capabilities.participant.session.runtime","Service OS cannot import participant session runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime","noetrium_platform.capabilities.participant.definition.runtime","Server session transport cannot import participant definition runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime","noetrium_platform.capabilities.participant.binding.runtime","Server session transport cannot import participant binding runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime","noetrium_platform.capabilities.participant.session.runtime","Server session transport cannot import participant session runtime"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime.","noetrium_platform.research.execution.runtime.manager","Persistent-session implementation cannot depend upward on Runtime Manager"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime.","noetrium_platform.infrastructure.lifecycle.service.runtime","Persistent-session implementation cannot own service supervision"),
    ImportRule("noetrium_platform.infrastructure.lifecycle.session.runtime.","noetrium_platform.capabilities.model.serving","Persistent-session implementation cannot own model serving"),
    ImportRule("noetrium_platform.research.execution.runtime.manager","noetrium_platform.infrastructure.lifecycle.session.runtime.","Runtime Manager must depend on persistent-session API, not a concrete backend"),
    ImportRule("noetrium_platform.foundation.governance.release.runtime","noetrium_platform.capabilities.participant.definition.runtime","Release identity layer cannot import participant definition runtime"),
    ImportRule("noetrium_platform.foundation.governance.release.runtime","noetrium_platform.capabilities.participant.binding.runtime","Release identity layer cannot import participant binding runtime"),
    ImportRule("noetrium_platform.foundation.governance.release.runtime","noetrium_platform.capabilities.participant.session.runtime","Release identity layer cannot import participant session runtime"),
    ImportRule("noetrium_platform.capabilities.participant.agent.api","noetrium_platform.capabilities.environment.runtime.api","Agent ABI cannot depend on Environment ABI"),
    ImportRule("noetrium_platform.capabilities.participant.agent.api","noetrium_platform.capabilities.participant.method.api","Agent ABI cannot depend on Method ABI"),
    ImportRule("noetrium_platform.capabilities.participant.agent.api","noetrium_platform.research.experimentation.study","Agent ABI cannot depend upward on Study runtime"),
    ImportRule("noetrium_platform.capabilities.participant.capability.api","noetrium_platform.capabilities.participant.agent.api","Capability ABI cannot depend upward on Agent ABI"),
    ImportRule("noetrium_platform.capabilities.participant.capability.api","noetrium_platform.capabilities.environment.runtime.api","Capability ABI cannot depend on Environment ABI"),
    ImportRule("noetrium_platform.capabilities.participant.capability.api","noetrium_platform.capabilities.participant.method.api","Capability ABI cannot depend on Method ABI"),
    ImportRule("noetrium_platform.capabilities.participant.capability.api","noetrium_platform.research.experimentation.study","Capability ABI cannot depend upward on Study runtime"),
    ImportRule("noetrium_platform.infrastructure.reliability.effect.api","noetrium_platform.capabilities.participant.agent.api","Effect ABI cannot depend upward on Agent ABI"),
    ImportRule("noetrium_platform.infrastructure.reliability.effect.api","noetrium_platform.capabilities.participant.capability.api","Effect ABI cannot depend upward on Capability ABI"),
    ImportRule("noetrium_platform.infrastructure.reliability.effect.api","noetrium_platform.capabilities.environment.runtime.api","Effect ABI cannot depend on Environment ABI"),
    ImportRule("noetrium_platform.infrastructure.reliability.effect.api","noetrium_platform.capabilities.participant.method.api","Effect ABI cannot depend on Method ABI"),
    ImportRule("noetrium_platform.infrastructure.reliability.effect.api","noetrium_platform.research.experimentation.study","Effect ABI cannot depend upward on Study runtime"),
    ImportRule("noetrium_platform.capabilities.participant.core.api","noetrium_platform.capabilities.participant.agent.api","Participant ABI cannot depend on Agent ABI"),
    ImportRule("noetrium_platform.capabilities.participant.core.api","noetrium_platform.capabilities.participant.capability.api","Participant ABI cannot depend on Capability ABI"),
    ImportRule("noetrium_platform.capabilities.participant.core.api","noetrium_platform.capabilities.environment.runtime.api","Participant ABI cannot depend on Environment ABI"),
    ImportRule("noetrium_platform.capabilities.participant.core.api","noetrium_platform.capabilities.participant.method.api","Participant ABI cannot depend on Method ABI"),
    ImportRule("noetrium_platform.capabilities.participant.core.api","noetrium_platform.research.experimentation.study","Participant ABI cannot depend upward on Study runtime"),
)


def architecture_import_rules(root: Path) -> tuple[ImportRule, ...]:
    from .extensions import discover_architecture_extensions

    rules = list(DEFAULT_IMPORT_RULES)
    for extension in discover_architecture_extensions(root):
        rules.extend(getattr(extension, "IMPORT_RULES", ()))
    return tuple(rules)
