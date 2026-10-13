from __future__ import annotations

"""Repository-wide finalization audit for the canonical Noetrium architecture.

The audit enforces the final Noetrium kernel: NoetriumUnit is the sole
semantic carrier; immutable research truth and authority-partitioned causal
Event Units are the semantic sources; declared/authorized/observed/evidenced
modalities never collapse; indexes/graphs/tables are rebuildable projections;
ticket-gated thin Providers form the physical ISA. It reports evidence and
never mutates source code.
"""

import ast
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Iterable, Mapping

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.providers import RepositorySourceTree

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)

from .composition.report import (
    ArchitectureReport,
    build_architecture_report as build_composed_architecture_report,
)
from .import_graph import (
    ImportEdge,
    _module_in_roots,
    _resolve_relative,
    audit_layer_dag,
)
from .source_authority import architecture_source_authority_rules
from .source_authority_matchers import resolved_call_name
from .ultimate_kernel_invariants import FORBIDDEN_LEGACY_MARKERS
SEMANTIC_ROOTS = (
    "noetrium",
    "noetrium_platform",
    "components",
    "orchestration",
    "projects",
)
OPERATIONAL_ROOTS = ("scripts",)
PRODUCTION_ROOTS = SEMANTIC_ROOTS
PUBLIC_ROOT_EXPORTS = (
    "NoetriumUnit",
    "run",
)
PUBLIC_ROOT_SYMBOLS = (
    "noetrium_platform.foundation.kernel.unit.NoetriumUnit",
    "noetrium._runtime.run",
)
CANONICAL_STRUCTURE_MODULES = (
    "noetrium_platform.foundation.kernel.unit",
    "noetrium_platform.foundation.kernel.structure",
    "noetrium_platform.foundation.kernel.calculus",
    "noetrium_platform.foundation.kernel.unit_identity",
    "noetrium_platform.foundation.kernel.unit_algebra",
    "noetrium_platform.foundation.kernel.unit_refinement",
    "noetrium_platform.foundation.kernel.unit_rewrite",
)
STALE_CARRIER_MODULES = (
    "noetrium_platform.foundation.kernel.graph",
    "noetrium_platform.foundation.kernel.graph_identity",
    "noetrium_platform.foundation.kernel.graph_algebra",
    "noetrium_platform.foundation.kernel.graph_refinement",
    "noetrium_platform.foundation.kernel.graph_rewrite",
    "noetrium_platform.foundation.kernel.implementation",
)
STALE_CARRIER_NAMES = frozenset({
    "NoetriumGraph",
    "GraphRef",
    "FailureEnvelope",
    "EffectIntent",
    "EffectIntentRecord",
    "EffectCompletionEvidence",
    "PreparedEffectHandle",
    "EffectResultSnapshot",
})
FORWARDING_FIELD_NAMES = frozenset({
    "_owner",
    "_delegate",
    "_inner",
    "_wrapped",
    "_target",
    "_runtime",
    "_provider",
    "_service",
    "_backend",
})
SIDE_PLANE_MODULE_MARKERS = (
    ".providers.",
    ".authority.",
    ".observability.",
    ".governance.",
    ".forensics.",
)
STRUCTURAL_FIELD_NAMES = frozenset({
    "children",
    "nodes",
    "edges",
    "relations",
    "dependencies",
    "dependency",
    "adjacency",
    "topological_order",
    "task_order",
    "lifecycle_order",
    "acquire_order",
    "release_order",
    "precedes",
    "upstream_refs",
    "downstream_refs",
})
STRUCTURAL_FIELD_PREFIXES = (
    "depends_on_",
    "prerequisite_",
)
STRUCTURAL_FIELD_SUFFIXES = (
    "_dependencies",
    "_dependency_ids",
    "_relations",
    "_edges",
)
HIGH_CONFIDENCE_STRUCTURAL_FIELDS = frozenset({
    "depends_on_task_ids", "retry_of_task_id", "task_order",
    "lifecycle_order", "resource_lifecycle_order", "precedes",
})
DYNAMIC_FIELD_TOKENS = (
    "state", "status", "generation", "lease", "owner", "phase", "running",
    "active", "allocated", "healthy", "ready",
)
RESOURCE_CONTROL_FIELD_MARKERS = (
    "authority_lease",
    "resource_lease",
    "lease_generation",
    "lease_expires",
    "fencing_token",
    "fence_generation",
    "resource_generation",
    "resource_claim",
    "realization_ticket",
    "allocation_generation",
    "allocated_gpu",
    "allocated_port",
    "allocated_endpoint",
    "resource_ownership",
)
DERIVED_NAME_TOKENS = (
    "Index", "Projection", "View", "Binding", "Frontier", "Interpreter",
    "Snapshot", "Report", "Receipt", "Result", "Diagnostic", "Plan",
    "Builder", "Compiled", "Bound", "Checkpoint", "Decision", "Inspection",
    "Coordinator", "Cache",
)
UNIVERSAL_AUTHORITY_SYMBOL = (
    "noetrium_platform.infrastructure.resources.authority.runtime.authority."
    "UniversalResourceAuthority"
)
RESOURCE_MODULE_PREFIX = "noetrium_platform.infrastructure.resources."
DOMAIN_AUTHORITY_NAME_TOKENS = (
    "Authority", "Scheduler", "Allocator", "LeaseRegistry",
)
AUTHORITY_POLICY_METHODS = frozenset({
    "acquire", "release", "renew", "reconcile", "recover", "recover_release",
    "advance_generation", "ensure_generation", "fence", "allocate", "admit",
    "prepare_realization", "begin_retire", "complete_retire", "park", "retain",
})
PROVIDER_POLICY_METHODS = frozenset({
    "acquire", "release", "renew", "reconcile", "recover", "recover_release",
    "advance_generation", "ensure_generation", "fence", "allocate", "admit",
    "reuse", "park", "retain", "schedule", "placement",
})
PROVIDER_MUTATION_METHODS = frozenset({
    "create", "start", "stop", "remove", "delete", "launch", "bind", "run",
    "realize", "retire",
})
ALGORITHM_FAMILIES: Mapping[str, tuple[str, ...]] = {
    "topological_order": (
        "topological_order",
        "_topological_order",
        "toposort",
    ),
    "reachability": (
        "reachable_downstream",
        "reachability",
    ),
    "dependency_frontier": (
        "ready_steps",
        "ready_targets",
        "dependency_frontier",
    ),
}
CANONICAL_ALGORITHMS: Mapping[str, str] = {
    "topological_order":
        "noetrium_platform.foundation.kernel.dag.deterministic_topological_order",
    "dependency_frontier":
        "noetrium_platform.foundation.kernel.structure.structure_ready_targets",
}
LEGACY_MARKERS = FORBIDDEN_LEGACY_MARKERS
HARD_KINDS = frozenset({
    "PUBLIC_ROOT_DRIFT", "PHYSICAL_EFFECT_BYPASS", "LAYER_BYPASS",
    "DUPLICATE_STRUCTURAL_TRUTH", "PARTIAL_MIGRATION", "LEGACY_PATH",
    "PARALLEL_RESOURCE_GRAPH_IR", "DOMAIN_SPECIFIC_AUTHORITY_DUPLICATION",
    "PROVIDER_OWNS_POLICY", "UNTICKETED_PROVIDER_MUTATION",
    "STALE_CARRIER",
    "CAUSAL_EVENT_KERNEL_INCOMPLETE",
    "TRUTH_MODALITY_INCOMPLETE",
    "DYNAMIC_EVENT_SOURCE_MISSING",
    "NON_REBUILDABLE_PROJECTION",
    "GLOBAL_EVENT_TOTAL_ORDER",
})
@dataclass(frozen=True, slots=True)
class FinalizationIssue:
    kind: str
    severity: str
    symbol: str
    path: str
    line: int
    detail: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalizationSymbol:
    symbol: str
    module: str
    name: str
    kind: str
    path: str
    line: int
    ast_nodes: int
    structural_fields: tuple[str, ...]
    dynamic_fields: tuple[str, ...]
    references: tuple[str, ...]
    classification: str
@dataclass(frozen=True, slots=True)
class FinalizationReport:
    source_root: str
    source_digest: str
    public_roots: tuple[str, ...]
    symbols: tuple[FinalizationSymbol, ...]
    issues: tuple[FinalizationIssue, ...]
    classification_counts: Mapping[str, int]
    issue_counts: Mapping[str, int]
    canonical_spine_modules: tuple[str, ...]
    canonical_spine_symbols: tuple[str, ...]
    orphan_modules: tuple[str, ...]
    identity_morphism_symbols: tuple[str, ...]
    architecture_clean: bool
    finalization_score: float
    clean: bool

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["classification_counts"] = dict(self.classification_counts)
        value["issue_counts"] = dict(self.issue_counts)
        return value


@dataclass(slots=True)
class _SymbolDraft:
    symbol: str
    module: str
    name: str
    kind: str
    path: str
    line: int
    ast_nodes: int
    fields: set[str] = field(default_factory=set)
    methods: set[str] = field(default_factory=set)
    immutable_value: bool = False
    protocol: bool = False
    raw_references: set[str] = field(default_factory=set)
    imports_graph: bool = False
    calls_graph: bool = False
    delegating: bool = False


def _module_for(relative_path: str) -> str:
    path = Path(relative_path).with_suffix("")
    parts = list(path.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _production_path(relative_path: str) -> bool:
    first = relative_path.split("/", 1)[0]
    return first in SEMANTIC_ROOTS


def _audited_path(relative_path: str) -> bool:
    first = relative_path.split("/", 1)[0]
    return first in SEMANTIC_ROOTS or first in OPERATIONAL_ROOTS


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None
def _structural_field(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(("_digest", "_identity", "_id")):
        return False
    return (
        lowered in STRUCTURAL_FIELD_NAMES
        or any(lowered.startswith(prefix) for prefix in STRUCTURAL_FIELD_PREFIXES)
        or any(lowered.endswith(suffix) for suffix in STRUCTURAL_FIELD_SUFFIXES)
    )


def _dynamic_field(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in DYNAMIC_FIELD_TOKENS)


def _class_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            fields.add(item.target.id)
    for item in ast.walk(node):
        if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else (item.target,)
            for target in targets:
                if isinstance(target, ast.Attribute):
                    name = _attribute_name(target)
                    if name and name.startswith("self."):
                        fields.add(name.split(".", 1)[1])
    return fields

def _class_methods(node: ast.ClassDef) -> set[str]:
    return {
        item.name
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not item.name.startswith("__")
    }


def _class_is_frozen_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = _attribute_name(decorator.func)
        if name is None and isinstance(decorator.func, ast.Name):
            name = decorator.func.id
        if name is None or name.rsplit(".", 1)[-1] != "dataclass":
            continue
        for keyword in decorator.keywords:
            if (
                keyword.arg == "frozen"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                return True
    return False


def _class_is_protocol(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        name = _attribute_name(base)
        if name is not None and name.rsplit(".", 1)[-1] == "Protocol":
            return True
    return False


def _semantic_body(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _function_is_delegate(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    body = _semantic_body(node.body)
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Return):
        return isinstance(statement.value, ast.Call)
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
    )


def _definition_is_delegate(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    fields: set[str],
) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _function_is_delegate(node)
    methods = [
        item
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not (
            item.name.startswith("__")
            and item.name.endswith("__")
        )
    ]
    if not methods:
        return False
    if fields and not fields.issubset(FORWARDING_FIELD_NAMES):
        return False
    return all(_function_is_delegate(item) for item in methods)


def _import_aliases(module: str, path: str, tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    source_is_package = path.endswith("/__init__.py")
    package = module.split(".") if source_is_package else module.split(".")[:-1]
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(0, len(package) - node.level + 1)
                prefix = package[:keep]
                if node.module:
                    prefix += node.module.split(".")
                base = ".".join(prefix)
            else:
                base = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = (
                    f"{base}.{alias.name}" if base else alias.name
                )
    return aliases


def _definition_references(
    node: ast.AST,
    *,
    module: str,
    local_names: frozenset[str],
    aliases: Mapping[str, str],
) -> tuple[set[str], bool]:
    refs: set[str] = set()
    calls_graph = False
    for item in ast.walk(node):
        if isinstance(item, ast.Name):
            if item.id in local_names:
                refs.add(f"{module}.{item.id}")
            target = aliases.get(item.id)
            if target:
                refs.add(target)
            if item.id == "NoetriumUnit":
                calls_graph = True
        elif isinstance(item, ast.Attribute):
            name = _attribute_name(item)
            if not name:
                continue
            head, _, tail = name.partition(".")
            target = aliases.get(head)
            if target and tail:
                refs.add(f"{target}.{tail}")
            if "NoetriumUnit" in name:
                calls_graph = True
    return refs, calls_graph


def _scan_symbols(
    source_index: RepositorySourceIndexPort,
    *,
    authority_rules=(),
) -> tuple[
    dict[str, _SymbolDraft],
    dict[str, set[str]],
    Counter[str],
    tuple[ImportEdge, ...],
    tuple[FinalizationIssue, ...],
]:
    drafts: dict[str, _SymbolDraft] = {}
    module_imports: dict[str, set[str]] = defaultdict(set)
    module_level_inbound: Counter[str] = Counter()
    import_edges: list[ImportEdge] = []
    authority_issues: list[FinalizationIssue] = []
    authority_rule_index: dict[str, list[object]] = defaultdict(list)
    for rule in authority_rules:
        final_name = rule.primitive.rsplit(".", 1)[-1]
        if final_name.endswith("(write-mode)"):
            final_name = final_name.split("(", 1)[0]
        authority_rule_index[final_name].append(rule)
    for blob in source_index.documents(suffixes={".py"}):
        if not _production_path(blob.relative_path):
            continue
        module = _module_for(blob.relative_path)
        tree = source_index.python_tree(blob.relative_path, sha256=blob.sha256)
        aliases = _import_aliases(module, blob.relative_path, tree)
        module_imports[module].update(aliases.values())
        nodes = source_index.python_nodes(blob.relative_path, sha256=blob.sha256)
        for item in nodes:
            if isinstance(item, ast.Import):
                for alias in item.names:
                    module_imports[module].add(alias.name)
                    if _module_in_roots(alias.name, PRODUCTION_ROOTS):
                        import_edges.append(ImportEdge(
                            module,
                            alias.name,
                            blob.relative_path,
                            item.lineno,
                        ))
            elif isinstance(item, ast.ImportFrom):
                target = (
                    _resolve_relative(
                        module,
                        item.level,
                        item.module,
                        source_is_package=blob.relative_path.endswith("/__init__.py"),
                    )
                    if item.level
                    else (item.module or "")
                )
                if target:
                    module_imports[module].add(target)
                if _module_in_roots(target, PRODUCTION_ROOTS):
                    import_edges.append(ImportEdge(
                        module,
                        target,
                        blob.relative_path,
                        item.lineno,
                    ))
            elif isinstance(item, ast.Call) and authority_rule_index:
                call_name = resolved_call_name(item, aliases) or ""
                final_name = call_name.rsplit(".", 1)[-1]
                for rule in authority_rule_index.get(final_name, ()):
                    if module in rule.allowed_modules or not rule.matches(item, aliases):
                        continue
                    authority_issues.append(FinalizationIssue(
                        "PHYSICAL_EFFECT_BYPASS",
                        "error",
                        module,
                        blob.relative_path,
                        item.lineno,
                        (
                            f"{rule.primitive} is a protected mutation primitive; "
                            f"authority belongs to {', '.join(rule.allowed_modules)}"
                        ),
                        (
                            f"authority={rule.authority}",
                            f"primitive={rule.primitive}",
                        ),
                    ))
        definitions = tuple(
            row
            for row in tree.body
            if isinstance(row, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        )
        local_names = frozenset(row.name for row in definitions)
        for statement in tree.body:
            if isinstance(
                statement,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            for item in ast.walk(statement):
                if isinstance(item, ast.Name) and item.id in local_names:
                    module_level_inbound[f"{module}.{item.id}"] += 1
        imports_graph = any(
            target.startswith(CANONICAL_STRUCTURE_MODULES)
            or target.endswith(".NoetriumUnit")
            for target in aliases.values()
        )
        for node in definitions:
            symbol = f"{module}.{node.name}"
            refs, calls_graph = _definition_references(
                node,
                module=module,
                local_names=local_names,
                aliases=aliases,
            )
            fields = _class_fields(node) if isinstance(node, ast.ClassDef) else set()
            methods = _class_methods(node) if isinstance(node, ast.ClassDef) else set()
            immutable_value = (
                _class_is_frozen_dataclass(node)
                if isinstance(node, ast.ClassDef)
                else False
            )
            protocol = (
                _class_is_protocol(node)
                if isinstance(node, ast.ClassDef)
                else False
            )
            drafts[symbol] = _SymbolDraft(
                symbol=symbol,
                module=module,
                name=node.name,
                kind="class" if isinstance(node, ast.ClassDef) else "function",
                path=blob.relative_path,
                line=node.lineno,
                ast_nodes=sum(1 for _ in ast.walk(node)),
                fields=fields,
                methods=methods,
                immutable_value=immutable_value,
                protocol=protocol,
                raw_references=refs,
                imports_graph=imports_graph,
                calls_graph=calls_graph,
                delegating=_definition_is_delegate(node, fields),
            )
    return (
        drafts,
        module_imports,
        module_level_inbound,
        tuple(import_edges),
        tuple(authority_issues),
    )


def _symbol_edges(
    drafts: Mapping[str, _SymbolDraft],
) -> tuple[dict[str, set[str]], Counter[str]]:
    known = set(drafts)
    edges: dict[str, set[str]] = {symbol: set() for symbol in drafts}
    inbound: Counter[str] = Counter()
    for symbol, draft in drafts.items():
        for reference in draft.raw_references:
            candidate = reference
            while candidate and candidate not in known and "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
            if candidate in known and candidate != symbol:
                edges[symbol].add(candidate)
                inbound[candidate] += 1
    return edges, inbound


def _module_graph(
    drafts: Mapping[str, _SymbolDraft],
    module_imports: Mapping[str, set[str]],
) -> dict[str, set[str]]:
    # Import-only package facades are real vertices: otherwise a local import
    # such as composition.operator.project stops at __init__.py and the audit
    # falsely marks its concrete loader/runtime as orphaned.
    modules = set(module_imports)
    modules.update(draft.module for draft in drafts.values())
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for source, targets in module_imports.items():
        if source not in graph:
            continue
        for target in targets:
            candidate = target
            while candidate not in modules and "." in candidate:
                candidate = candidate.rsplit(".", 1)[0]
            if candidate in modules and candidate != source:
                graph[source].add(candidate)
    return graph


def _reachable(
    graph: Mapping[str, set[str]],
    roots: Iterable[str],
) -> set[str]:
    seen: set[str] = set()
    queue = deque(root for root in roots if root in graph)
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(graph[current] - seen)
    return seen


def _derived_symbol(draft: _SymbolDraft) -> bool:
    return any(token in draft.name for token in DERIVED_NAME_TOKENS)


def _universal_authority_symbol(draft: _SymbolDraft) -> bool:
    return draft.symbol == UNIVERSAL_AUTHORITY_SYMBOL


def _provider_symbol(draft: _SymbolDraft) -> bool:
    return (
        draft.module.startswith(RESOURCE_MODULE_PREFIX)
        and ".providers." in draft.module
        and draft.kind == "class"
        and "Provider" in draft.name
    )


def _domain_authority_symbol(draft: _SymbolDraft) -> bool:
    if not draft.module.startswith(RESOURCE_MODULE_PREFIX):
        return False
    if draft.module.startswith(
        "noetrium_platform.infrastructure.resources.authority."
    ):
        return False
    if ".api." in draft.module:
        return False
    if _universal_authority_symbol(draft) or _provider_symbol(draft):
        return False
    if draft.kind != "class":
        return False
    named = any(token in draft.name for token in DOMAIN_AUTHORITY_NAME_TOKENS)
    owns_policy = bool(draft.methods & AUTHORITY_POLICY_METHODS)
    owns_dynamic = any(_dynamic_field(field) for field in draft.fields)
    return named and (owns_policy or owns_dynamic)


def _canonical_structure_symbol(draft: _SymbolDraft) -> bool:
    return draft.module.startswith(CANONICAL_STRUCTURE_MODULES)


def _algorithm_family(name: str) -> str | None:
    lowered = name.lower()
    for family, tokens in ALGORITHM_FAMILIES.items():
        if any(token in lowered for token in tokens):
            return family
    return None


def _public_roots(source_index: RepositorySourceIndexPort) -> tuple[str, ...]:
    tree = source_index.python_tree("noetrium/api/__init__.py")
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            return ()
        if isinstance(value, tuple) and all(isinstance(row, str) for row in value):
            return tuple(value)
    return ()


def _structural_issues(
    drafts: Mapping[str, _SymbolDraft],
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        structural = tuple(
            sorted(field for field in draft.fields if _structural_field(field))
        )
        if not structural:
            continue
        if (
            _canonical_structure_symbol(draft)
            or _derived_symbol(draft)
            or _universal_authority_symbol(draft)
            or draft.module.startswith(
                "noetrium_platform.foundation.governance."
            )
        ):
            continue
        high = tuple(
            field
            for field in structural
            if field in HIGH_CONFIDENCE_STRUCTURAL_FIELDS
        )
        if high:
            issues.append(FinalizationIssue(
                "DUPLICATE_STRUCTURAL_TRUTH",
                "error",
                draft.symbol,
                draft.path,
                draft.line,
                "class stores structural truth already owned by recursive NoetriumUnit",
                high,
            ))
            continue
        # Private runtime working structures are not independent domain
        # truth. They may use graph-like shapes (tries, dependency sets, search
        # state) for optimal algorithms or Authority-local mutable state. They
        # remain implementation details precisely because they are private,
        # runtime-local, and do not import/call the canonical structural kernel.
        if (
            draft.symbol.rsplit(".", 1)[-1].startswith("_")
            and ".runtime." in draft.module
            and not draft.imports_graph
            and not draft.calls_graph
        ):
            continue
        if draft.imports_graph or draft.calls_graph:
            issues.append(FinalizationIssue(
                "PARTIAL_MIGRATION",
                "error",
                draft.symbol,
                draft.path,
                draft.line,
                "class uses NoetriumUnit while also storing an independent structural topology",
                structural,
            ))
        else:
            issues.append(FinalizationIssue(
                "STRUCTURAL_TRUTH_SUSPECT",
                "warning",
                draft.symbol,
                draft.path,
                draft.line,
                "class stores graph-like structure outside the canonical graph kernel",
                structural,
            ))
    return issues
def _resource_control_dynamic_field(name: str) -> bool:
    lowered = name.lower().lstrip("_")
    if lowered.endswith((
        "_id", "_key", "_ref", "_path", "_root", "_group",
        "_factory", "_handle",
    )):
        return False
    return any(marker in lowered for marker in RESOURCE_CONTROL_FIELD_MARKERS)


def _references_resource_control(draft: _SymbolDraft) -> bool:
    if draft.module.startswith(RESOURCE_MODULE_PREFIX):
        return True
    resource_contracts = (
        "ResourceAuthorityPort",
        "UniversalResourceAuthority",
        "resource_claim",
        "claim_field",
        "authority_lease",
        "lease_field",
        "realization_ticket",
        "ticket_field",
        "PhysicalResourceProvider",
        "ResourceCapacity",
        "ResourceRealizationSpec",
    )
    return any(
        any(token in reference for token in resource_contracts)
        for reference in draft.raw_references
    )


def _dynamic_truth_issues(
    drafts: Mapping[str, _SymbolDraft],
) -> list[FinalizationIssue]:
    """Find duplicated *resource-control* truth, not arbitrary runtime state.

    Domain state machines, locks, caches, error phases and immutable projections
    are legitimate local state. The Universal Resource Authority exclusively
    owns resource claims, lease generations/fences and concrete allocation
    ownership. Only fields that encode those facts are candidates here.
    """

    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        dynamic = tuple(
            sorted(
                field
                for field in draft.fields
                if _resource_control_dynamic_field(field)
            )
        )
        if not dynamic:
            continue
        if not _references_resource_control(draft):
            continue
        if draft.immutable_value or draft.protocol:
            continue
        if _universal_authority_symbol(draft) or _derived_symbol(draft):
            continue
        if _provider_symbol(draft):
            continue
        issues.append(FinalizationIssue(
            "DYNAMIC_TRUTH_SUSPECT",
            "warning",
            draft.symbol,
            draft.path,
            draft.line,
            "resource-control truth is stored outside UniversalResourceAuthority",
            dynamic,
        ))
    return issues


def _authority_provider_issues(
    drafts: Mapping[str, _SymbolDraft],
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        if _domain_authority_symbol(draft):
            policy = tuple(sorted(draft.methods & AUTHORITY_POLICY_METHODS))
            dynamic = tuple(sorted(
                field for field in draft.fields if _dynamic_field(field)
            ))
            issues.append(FinalizationIssue(
                "DOMAIN_SPECIFIC_AUTHORITY_DUPLICATION",
                "error",
                draft.symbol,
                draft.path,
                draft.line,
                "resource domain owns mutable lifecycle policy outside UniversalResourceAuthority",
                policy + dynamic,
            ))
            continue
        if not _provider_symbol(draft):
            continue
        policy = tuple(sorted(draft.methods & PROVIDER_POLICY_METHODS))
        if policy:
            issues.append(FinalizationIssue(
                "PROVIDER_OWNS_POLICY",
                "error",
                draft.symbol,
                draft.path,
                draft.line,
                "physical Provider owns lifecycle/placement/recovery policy reserved for Authority",
                policy,
            ))
        mutation = tuple(sorted(draft.methods & PROVIDER_MUTATION_METHODS))
        ticket_gated = any(
            reference == "ticket_field"
            or reference.endswith(".ticket_field")
            or reference == "is_realization_ticket"
            or reference.endswith(".is_realization_ticket")
            for reference in draft.raw_references
        )
        if mutation and not ticket_gated:
            issues.append(FinalizationIssue(
                "UNTICKETED_PROVIDER_MUTATION",
                "error",
                draft.symbol,
                draft.path,
                draft.line,
                "physical mutation is exposed without the canonical resource.ticket Unit contract",
                mutation,
            ))
    return issues


def _algorithm_issues(
    drafts: Mapping[str, _SymbolDraft],
) -> list[FinalizationIssue]:
    grouped: dict[str, list[_SymbolDraft]] = defaultdict(list)
    for draft in drafts.values():
        family = _algorithm_family(draft.name)
        if family and draft.ast_nodes >= 18 and draft.kind == "function":
            grouped[family].append(draft)
    issues: list[FinalizationIssue] = []
    for family, rows in grouped.items():
        canonical = CANONICAL_ALGORITHMS.get(family)
        substantial = [row for row in rows if row.symbol != canonical]
        if len(substantial) < 2 and canonical is None:
            continue
        for row in substantial:
            if row.delegating:
                continue
            if row.name.startswith("execution_graph_"):
                continue
            if canonical and canonical in row.raw_references:
                continue
            if canonical and any(
                reference in drafts
                and canonical in drafts[reference].raw_references
                for reference in row.raw_references
            ):
                continue
            peers = tuple(
                candidate.symbol
                for candidate in rows
                if candidate.symbol != row.symbol
            )
            evidence = (
                (f"canonical={canonical}",) if canonical else ()
            ) + peers[:6]
            issues.append(FinalizationIssue(
                "ALGORITHM_DUPLICATION_SUSPECT",
                "warning",
                row.symbol,
                row.path,
                row.line,
                f"independent implementation belongs to algorithm family {family!r}",
                evidence,
            ))
    return issues


def _dead_symbol_issues(
    drafts: Mapping[str, _SymbolDraft],
    inbound: Counter[str],
    reachable_modules: set[str],
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        if draft.symbol in PUBLIC_ROOT_SYMBOLS:
            continue
        if draft.module in reachable_modules or inbound[draft.symbol] > 0:
            continue
        if not draft.name.startswith("_") or draft.name.startswith("__"):
            continue
        issues.append(FinalizationIssue(
            "DEAD_SYMBOL_SUSPECT",
            "warning",
            draft.symbol,
            draft.path,
            draft.line,
            "private production symbol has no inbound reference and its module is outside the canonical root closure",
        ))
    return issues


def _legacy_issues(
    source_index: RepositorySourceIndexPort,
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for blob in source_index.documents(suffixes={".py"}):
        if not _audited_path(blob.relative_path):
            continue
        for marker in LEGACY_MARKERS:
            if marker not in blob.text:
                continue
            if blob.relative_path.endswith((
                "ultimate_kernel_invariants.py",
                "finalization.py",
            )):
                continue
            line = blob.text[: blob.text.index(marker)].count("\n") + 1
            issues.append(FinalizationIssue(
                "LEGACY_PATH",
                "error",
                marker,
                blob.relative_path,
                line,
                "forbidden pre-finalization semantic path remains in production source",
            ))
    return issues


def _stale_carrier_issues(
    source_index: RepositorySourceIndexPort,
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for blob in source_index.documents(suffixes={".py"}):
        if not _audited_path(blob.relative_path):
            continue
        tree = source_index.python_tree(blob.relative_path, sha256=blob.sha256)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == stale or alias.name.startswith(stale + ".")
                        for stale in STALE_CARRIER_MODULES
                    ):
                        issues.append(FinalizationIssue(
                            "STALE_CARRIER", "error", alias.name,
                            blob.relative_path, node.lineno,
                            "removed pre-Unit kernel module remains imported",
                        ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == stale or module.startswith(stale + ".")
                    for stale in STALE_CARRIER_MODULES
                ):
                    issues.append(FinalizationIssue(
                        "STALE_CARRIER", "error", module,
                        blob.relative_path, node.lineno,
                        "removed pre-Unit kernel module remains imported",
                    ))
                for alias in node.names:
                    if alias.name in STALE_CARRIER_NAMES:
                        issues.append(FinalizationIssue(
                            "STALE_CARRIER", "error", alias.name,
                            blob.relative_path, node.lineno,
                            "removed carrier type remains imported",
                        ))
            elif isinstance(node, ast.ClassDef) and node.name in STALE_CARRIER_NAMES:
                issues.append(FinalizationIssue(
                    "STALE_CARRIER", "error", node.name,
                    blob.relative_path, node.lineno,
                    "removed carrier type remains defined",
                ))
            elif isinstance(node, ast.Call):
                name = _attribute_name(node.func)
                if name is None and isinstance(node.func, ast.Name):
                    name = node.func.id
                if name and name.rsplit(".", 1)[-1] in STALE_CARRIER_NAMES:
                    issues.append(FinalizationIssue(
                        "STALE_CARRIER", "error", name,
                        blob.relative_path, node.lineno,
                        "removed carrier type remains constructed",
                    ))
    unique: dict[tuple[str, str, int, str], FinalizationIssue] = {}
    for row in issues:
        unique[(row.kind, row.path, row.line, row.symbol)] = row
    return list(unique.values())


def _identity_morphism_issues(
    drafts: Mapping[str, _SymbolDraft],
    *,
    symbol_reachable: set[str],
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        if not draft.delegating or draft.kind != "class":
            continue
        if draft.symbol in PUBLIC_ROOT_SYMBOLS:
            continue
        if (
            draft.module.endswith(".method.authoring")
            and draft.name.startswith("Research")
            and draft.name.endswith("DSL")
        ):
            # Typed authoring vocabularies are pure derived views over the
            # universal Method/Unit builder. They add no runtime truth, state,
            # authority, effect, or recovery law and therefore are not layers.
            continue
        if (
            draft.protocol
            or draft.immutable_value
            or _canonical_structure_symbol(draft)
            or _universal_authority_symbol(draft)
            or _provider_symbol(draft)
            or any(marker in draft.module for marker in SIDE_PLANE_MODULE_MARKERS)
        ):
            continue
        issues.append(FinalizationIssue(
            "IDENTITY_MORPHISM_LAYER",
            "warning",
            draft.symbol,
            draft.path,
            draft.line,
            (
                "definition owns no independent state/authority and only forwards "
                "one adjacent call; inline or remove unless it is a deliberate public view"
            ),
            (
                "symbol_spine=yes"
                if draft.symbol in symbol_reachable
                else "symbol_spine=no",
            ),
        ))
    return issues


def _orphan_modules(
    drafts: Mapping[str, _SymbolDraft],
    module_graph: Mapping[str, set[str]],
    reachable_modules: set[str],
) -> tuple[str, ...]:
    inbound: Counter[str] = Counter()
    for source, targets in module_graph.items():
        for target in targets:
            if target != source:
                inbound[target] += 1
    by_module: dict[str, list[_SymbolDraft]] = defaultdict(list)
    for draft in drafts.values():
        by_module[draft.module].append(draft)
    rows: list[str] = []
    for module, definitions in by_module.items():
        if module in reachable_modules or inbound[module] > 0:
            continue
        if any(marker in module for marker in SIDE_PLANE_MODULE_MARKERS):
            continue
        if all(
            row.protocol or row.immutable_value or _derived_symbol(row)
            for row in definitions
        ):
            continue
        rows.append(module)
    return tuple(sorted(rows))


def _resource_ir_issues(
    drafts: Mapping[str, _SymbolDraft],
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for draft in drafts.values():
        if draft.name != "ResourceGraph":
            continue
        issues.append(FinalizationIssue(
            "PARALLEL_RESOURCE_GRAPH_IR",
            "error",
            draft.symbol,
            draft.path,
            draft.line,
            "resource structure must use NoetriumUnit rather than a parallel ResourceGraph entity",
        ))
    return issues



def _causal_unit_invariant_issues(root: Path) -> list[FinalizationIssue]:
    """Enforce the Unit + authority-partitioned causal Event final form."""

    root = Path(root)
    issues: list[FinalizationIssue] = []
    required: Mapping[str, tuple[tuple[str, str], ...]] = {
        "noetrium_platform/foundation/kernel/truth.py": (
            ("TRUTH_MODALITY_INCOMPLETE", 'DECLARED = "declared"'),
            ("TRUTH_MODALITY_INCOMPLETE", 'AUTHORIZED = "authorized"'),
            ("TRUTH_MODALITY_INCOMPLETE", 'OBSERVED = "observed"'),
            ("TRUTH_MODALITY_INCOMPLETE", 'EVIDENCED = "evidenced"'),
        ),
        "noetrium_platform/foundation/kernel/event.py": (
            ("CAUSAL_EVENT_KERNEL_INCOMPLETE", "def causal_event("),
            ("CAUSAL_EVENT_KERNEL_INCOMPLETE", "def events_independent("),
            ("CAUSAL_EVENT_KERNEL_INCOMPLETE", "def causal_topological_order("),
            ("CAUSAL_EVENT_KERNEL_INCOMPLETE", "def reverse_causal_cone("),
            ("CAUSAL_EVENT_KERNEL_INCOMPLETE", 'EVENT_SCHEMA = "system.event"'),
        ),
        "noetrium_platform/infrastructure/resources/authority/runtime/authority.py": (
            ("DYNAMIC_EVENT_SOURCE_MISSING", "resource_authority_events"),
            ("DYNAMIC_EVENT_SOURCE_MISSING", "resource_authority_event_heads"),
            ("NON_REBUILDABLE_PROJECTION", "def project_snapshot_from_events("),
            ("NON_REBUILDABLE_PROJECTION", "def verify_projection_rebuild("),
        ),
        "noetrium_platform/infrastructure/reliability/effect/runtime/sqlite_backend.py": (
            ("DYNAMIC_EVENT_SOURCE_MISSING", "effect_events"),
            ("DYNAMIC_EVENT_SOURCE_MISSING", "current_event_digest"),
        ),
        "noetrium_platform/infrastructure/reliability/effect/runtime/persistent.py": (
            ("NON_REBUILDABLE_PROJECTION", "def verify_projection_rebuild("),
            ("DYNAMIC_EVENT_SOURCE_MISSING", "effect_record_event("),
        ),
        "noetrium_platform/infrastructure/reliability/failure/api/failure_units.py": (
            ("DYNAMIC_EVENT_SOURCE_MISSING", "causal_event("),
            ("TRUTH_MODALITY_INCOMPLETE", "TruthModality.EVIDENCED"),
            ("DYNAMIC_EVENT_SOURCE_MISSING", "event_kind=_FAILURE_KIND"),
        ),
        "noetrium_platform/infrastructure/reliability/forensics/api/mutation.py": (
            ("DYNAMIC_EVENT_SOURCE_MISSING", "def mutation_event("),
            ("TRUTH_MODALITY_INCOMPLETE", "TruthModality.AUTHORIZED"),
            ("DYNAMIC_EVENT_SOURCE_MISSING", 'event_kind="state.mutation"'),
        ),
        "noetrium_platform/infrastructure/reliability/forensics/runtime/runtime_bundle.py": (
            ("NON_REBUILDABLE_PROJECTION", "def verify_failure_projection_rebuild("),
            ("NON_REBUILDABLE_PROJECTION", "def verify_mutation_projection_rebuild("),
        ),
        "noetrium_platform/research/experimentation/scientific_evidence.py": (
            ("TRUTH_MODALITY_INCOMPLETE", "TruthModality.EVIDENCED"),
            ("TRUTH_MODALITY_INCOMPLETE", "modal_attributes("),
        ),
    }
    for relative, checks in required.items():
        path = root / relative
        if not path.is_file():
            issues.append(FinalizationIssue(
                "CAUSAL_EVENT_KERNEL_INCOMPLETE", "error",
                relative, relative, 1,
                "required final-form Unit/Event module is missing",
            ))
            continue
        text = path.read_text(encoding="utf-8")
        for kind, token in checks:
            if token in text:
                continue
            issues.append(FinalizationIssue(
                kind, "error", relative, relative, 1,
                "required final-form invariant is absent",
                (f"missing={token}",),
            ))

    forbidden_names = frozenset({
        "global_sequence",
        "global_sequence_number",
        "global_event_sequence",
        "event_sequence_number",
        "global_event_order",
        "total_event_order",
    })
    event_paths = (
        "noetrium_platform/foundation/kernel/event.py",
        "noetrium_platform/infrastructure/resources/authority/runtime/authority.py",
        "noetrium_platform/infrastructure/reliability/effect/runtime/sqlite_backend.py",
        "noetrium_platform/infrastructure/reliability/forensics/runtime/runtime_bundle.py",
    )
    for relative in event_paths:
        path = root / relative
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.arg):
                name = node.arg
            if name not in forbidden_names:
                continue
            issues.append(FinalizationIssue(
                "GLOBAL_EVENT_TOTAL_ORDER", "error", str(name),
                relative, getattr(node, "lineno", 1),
                "global event ordering is forbidden; causal/domain ordering is sufficient",
            ))
    return issues


def _architecture_issues(
    report: ArchitectureReport,
) -> list[FinalizationIssue]:
    issues: list[FinalizationIssue] = []
    for row in report.source_authority_violations:
        issues.append(FinalizationIssue(
            "PHYSICAL_EFFECT_BYPASS",
            "error",
            row.module,
            row.path,
            row.line,
            row.detail,
            (f"authority={row.authority}", f"primitive={row.primitive}"),
        ))
    for row in report.layer_violations:
        issues.append(FinalizationIssue(
            "LAYER_BYPASS",
            "error",
            row.source,
            row.path,
            row.line,
            row.reason,
            (f"target={row.target}", f"{row.source_layer}->{row.target_layer}"),
        ))
    return issues


def _classify_symbol(
    draft: _SymbolDraft,
    *,
    reachable_modules: set[str],
    symbol_reachable: set[str],
    inbound: Counter[str],
) -> str:
    if draft.symbol in PUBLIC_ROOT_SYMBOLS:
        return "ENTRYPOINT"
    if _canonical_structure_symbol(draft):
        return "CANONICAL"
    if _universal_authority_symbol(draft):
        return "UNIVERSAL_AUTHORITY"
    if _provider_symbol(draft):
        return "THIN_PROVIDER"
    if _domain_authority_symbol(draft):
        return "DOMAIN_AUTHORITY_LEGACY"
    if _derived_symbol(draft):
        return "DERIVED"
    if draft.symbol in symbol_reachable:
        return "CANONICAL_SPINE"
    if draft.module in reachable_modules:
        return "MODULE_REACHABLE"
    if inbound[draft.symbol] == 0:
        return "SUSPECT"
    return "SIDE_REACHABLE"


def build_finalization_report(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort | None = None,
    full: bool = False,
) -> FinalizationReport:
    root = Path(root).resolve()
    if source_index is not None:
        index = source_index
    elif full:
        index = RepositorySourceTree(
            root,
            included_root_directories=frozenset((*SEMANTIC_ROOTS, *OPERATIONAL_ROOTS)),
        ).index()
    else:
        index = RepositorySourceTree(
            root,
            included_root_directories=frozenset((*SEMANTIC_ROOTS, *OPERATIONAL_ROOTS)),
        ).index()
    (
        drafts,
        module_imports,
        module_level_inbound,
        import_edges,
        quick_authority_issues,
    ) = _scan_symbols(
        index,
        authority_rules=(
            ()
            if full
            else architecture_source_authority_rules(root)
        ),
    )
    if full:
        # Reuse the exact working-tree source cut for the canonical architecture
        # gate. The composed report still compares filesystem cuts to Git HEAD.
        architecture = build_composed_architecture_report(
            root,
            source_index=index,
        )
        architecture_issues = _architecture_issues(architecture)
        architecture_clean = architecture.clean
    else:
        layer_violations = audit_layer_dag(root, import_edges)
        architecture_issues = list(quick_authority_issues)
        architecture_issues.extend(
            FinalizationIssue(
                "LAYER_BYPASS",
                "error",
                row.edge.source_module,
                row.edge.path,
                row.edge.line,
                row.reason,
                (
                    f"target={row.edge.target_module}",
                    f"{row.source_layer}->{row.target_layer}",
                ),
            )
            for row in layer_violations
        )
        architecture_clean = not architecture_issues
    symbol_graph, inbound = _symbol_edges(drafts)
    inbound.update(module_level_inbound)
    symbol_reachable = _reachable(symbol_graph, PUBLIC_ROOT_SYMBOLS)
    module_graph = _module_graph(drafts, module_imports)
    root_modules = {
        symbol.rsplit(".", 1)[0]
        for symbol in PUBLIC_ROOT_SYMBOLS
    }
    reachable_modules = _reachable(module_graph, root_modules)
    orphan_modules = _orphan_modules(drafts, module_graph, reachable_modules)
    public_roots = _public_roots(index)

    issues: list[FinalizationIssue] = []
    if public_roots != PUBLIC_ROOT_EXPORTS:
        issues.append(FinalizationIssue(
            "PUBLIC_ROOT_DRIFT",
            "error",
            "noetrium.__all__",
            "noetrium/api/__init__.py",
            1,
            "public API must expose exactly the canonical Unit/run roots",
            (
                f"actual={public_roots!r}",
                f"expected={PUBLIC_ROOT_EXPORTS!r}",
            ),
        ))
    issues.extend(architecture_issues)
    issues.extend(_causal_unit_invariant_issues(root))
    issues.extend(_structural_issues(drafts))
    issues.extend(_dynamic_truth_issues(drafts))
    issues.extend(_authority_provider_issues(drafts))
    issues.extend(_algorithm_issues(drafts))
    issues.extend(_dead_symbol_issues(
        drafts,
        inbound,
        reachable_modules,
    ))
    issues.extend(_identity_morphism_issues(
        drafts,
        symbol_reachable=symbol_reachable,
    ))
    issues.extend(_stale_carrier_issues(index))
    issues.extend(_legacy_issues(index))
    issues.extend(_resource_ir_issues(drafts))
    issues.sort(key=lambda row: (
        0 if row.severity == "error" else 1,
        row.kind,
        row.path,
        row.line,
        row.symbol,
    ))

    symbols = tuple(
        FinalizationSymbol(
            symbol=draft.symbol,
            module=draft.module,
            name=draft.name,
            kind=draft.kind,
            path=draft.path,
            line=draft.line,
            ast_nodes=draft.ast_nodes,
            structural_fields=tuple(sorted(
                field
                for field in draft.fields
                if _structural_field(field)
            )),
            dynamic_fields=tuple(sorted(
                field
                for field in draft.fields
                if _dynamic_field(field)
            )),
            references=tuple(sorted(draft.raw_references)),
            classification=_classify_symbol(
                draft,
                reachable_modules=reachable_modules,
                symbol_reachable=symbol_reachable,
                inbound=inbound,
            ),
        )
        for draft in sorted(
            drafts.values(),
            key=lambda row: row.symbol,
        )
    )
    classification_counts = Counter(
        row.classification
        for row in symbols
    )
    issue_counts = Counter(row.kind for row in issues)
    hard_count = sum(row.kind in HARD_KINDS for row in issues)
    warning_count = len(issues) - hard_count
    weighted_findings = hard_count * 3.0 + warning_count * 0.2
    score = max(
        0.0,
        round(
            100.0
            * (1.0 - weighted_findings / max(1.0, float(len(symbols)))),
            2,
        ),
    )
    clean = hard_count == 0 and architecture_clean
    return FinalizationReport(
        source_root=str(root),
        source_digest=index.source_digest,
        public_roots=public_roots,
        symbols=symbols,
        issues=tuple(issues),
        classification_counts=dict(sorted(classification_counts.items())),
        issue_counts=dict(sorted(issue_counts.items())),
        canonical_spine_modules=tuple(sorted(reachable_modules)),
        canonical_spine_symbols=tuple(sorted(symbol_reachable)),
        orphan_modules=orphan_modules,
        identity_morphism_symbols=tuple(sorted(
            row.symbol
            for row in issues
            if row.kind == "IDENTITY_MORPHISM_LAYER"
        )),
        architecture_clean=architecture_clean,
        finalization_score=score,
        clean=clean,
    )


def render_finalization_markdown(
    report: FinalizationReport,
) -> str:
    hard = [
        row for row in report.issues
        if row.severity == "error"
    ]
    warnings = [
        row for row in report.issues
        if row.severity != "error"
    ]
    lines = [
        "# Noetrium Finalization Audit",
        "",
        f"- Finalization score: **{report.finalization_score:.2f}%**",
        f"- Hard violations: **{len(hard)}**",
        f"- Suspects: **{len(warnings)}**",
        f"- Architecture gate clean: **{report.architecture_clean}**",
        f"- Public roots: `{', '.join(report.public_roots)}`",
        "",
        "## Canonical architecture",
        "",
        "`Immutable Recursive Content-Addressed NoetriumUnit + Authority-Partitioned Causal Event Units → "
        "Rebuildable Disposable Projections → Thin Providers → Physical World`",
        "",
        "## Classification",
        "",
    ]
    for key, value in report.classification_counts.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Findings", ""])
    for issue in report.issues:
        evidence = "; ".join(issue.evidence)
        suffix = f" — {evidence}" if evidence else ""
        lines.append(
            f"- **{issue.severity.upper()} {issue.kind}** "
            f"`{issue.symbol}` at `{issue.path}:{issue.line}`: "
            f"{issue.detail}{suffix}"
        )
    if not report.issues:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def write_finalization_artifacts(
    report: FinalizationReport,
    output_root: Path,
) -> tuple[Path, Path, Path]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "report.json"
    suspects_path = output_root / "suspects.md"
    spine_path = output_root / "canonical-spine.md"
    atomic_replace_bytes(
        report_path,
        json.dumps(
            report.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8"),
    )
    atomic_replace_bytes(
        suspects_path,
        render_finalization_markdown(report).encode("utf-8"),
    )
    spine_lines = [
        "# Canonical Noetrium Spine",
        "",
        "Four public roots:",
        *[f"- `{name}`" for name in report.public_roots],
        "",
        "Reachable production modules:",
        *[
            f"- `{module}`"
            for module in report.canonical_spine_modules
        ],
        "",
    ]
    atomic_replace_bytes(
        spine_path,
        "\n".join(spine_lines).encode("utf-8"),
    )
    return report_path, suspects_path, spine_path


__all__ = [
    "FinalizationIssue",
    "FinalizationReport",
    "FinalizationSymbol",
    "build_finalization_report",
    "render_finalization_markdown",
    "write_finalization_artifacts",
]
