from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .audit import AuditViolation
from .budget import (
    ArchitectureBudgetViolation,
    ArchitectureComplexity,
    ArchitectureComplexityBudget,
    audit_architecture_complexity_budget,
)
from .hotspots import ModuleHotspot
from .import_graph import (
    ImportViolation,
    LayerViolation,
    architecture_import_rules,
    audit_import_rules,
    audit_layer_dag,
    package_cycles,
)
from .optimization import ModuleOptimizationProfile
from .platform_policy import build_platform_audit
from .seam_graphs import SeamEdge, declared_capability_graph, partition_seam_graphs
from .source_authority import architecture_source_authority_rules
from .source_authority_contracts import SourceAuthorityViolation
from .source_index import architecture_source_index
from .source_invariants import audit_source_invariants
from .source_profile import scan_architecture_source_profile
from .source_scan import SourceInvariantViolation
from .system_graphs import (
    SubsystemGraphEdge,
    SystemGraphEdge,
    declared_subsystem_graph,
    declared_system_graph,
)


@dataclass(frozen=True, slots=True)
class ImportViolationRecord:
    source: str
    target: str
    path: str
    line: int
    reason: str

    @classmethod
    def from_violation(cls, violation: ImportViolation) -> "ImportViolationRecord":
        return cls(
            source=violation.edge.source_module,
            target=violation.edge.target_module,
            path=violation.edge.path,
            line=violation.edge.line,
            reason=violation.reason,
        )


@dataclass(frozen=True, slots=True)
class LayerViolationRecord:
    source: str
    target: str
    path: str
    line: int
    source_layer: str
    target_layer: str
    reason: str

    @classmethod
    def from_violation(cls, violation: LayerViolation) -> "LayerViolationRecord":
        return cls(
            source=violation.edge.source_module,
            target=violation.edge.target_module,
            path=violation.edge.path,
            line=violation.edge.line,
            source_layer=violation.source_layer,
            target_layer=violation.target_layer,
            reason=violation.reason,
        )


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    source_root: str
    source_digest: str
    import_edges: int
    import_violations: tuple[ImportViolationRecord, ...]
    layer_violations: tuple[LayerViolationRecord, ...]
    package_cycles: tuple[tuple[str, ...], ...]
    declared_authority_violations: tuple[AuditViolation, ...]
    source_invariant_violations: tuple[SourceInvariantViolation, ...]
    source_authority_violations: tuple[SourceAuthorityViolation, ...]
    architecture_complexity: ArchitectureComplexity
    architecture_complexity_budget: ArchitectureComplexityBudget | None
    architecture_budget_violations: tuple[ArchitectureBudgetViolation, ...]
    top_hotspots: tuple[ModuleHotspot, ...]
    top_optimization_risks: tuple[ModuleOptimizationProfile, ...]
    capability_graph: tuple[SeamEdge, ...]
    operation_graph: tuple[SeamEdge, ...]
    event_graph: tuple[SeamEdge, ...]
    system_graph: tuple[SystemGraphEdge, ...]
    subsystem_graph: tuple[SubsystemGraphEdge, ...]
    report_sha256: str

    @property
    def clean(self) -> bool:
        return not (
            self.import_violations
            or self.layer_violations
            or self.package_cycles
            or self.declared_authority_violations
            or self.source_invariant_violations
            or self.source_authority_violations
            or self.architecture_budget_violations
        )


def build_architecture_report(
    root: Path,
    *,
    hotspot_limit: int = 20,
    source_index: RepositorySourceIndexPort | None = None,
) -> ArchitectureReport:
    root = Path(root).resolve()
    if source_index is None:
        from .composition.report import build_architecture_report as compose_architecture_report

        return compose_architecture_report(root, hotspot_limit=hotspot_limit)
    authority_rules = architecture_source_authority_rules(root)
    profile = scan_architecture_source_profile(
        root, source_index=source_index, authority_rules=authority_rules
    )
    with architecture_source_index(
        root, max_entries=128, repository_index=source_index
    ) as architecture_index:
        architecture_index.seed_imports(
            (root / fact.path, fact.imports) for fact in profile.import_facts
        )
        architecture_index.seed_import_edges(("noetrium_platform", "components", "orchestration", "projects", "noetrium"), profile.import_edges)
        architecture_index.seed_import_edges(
            ("noetrium_platform", "components", "orchestration", "noetrium"),
            (
                edge
                for edge in profile.import_edges
                if edge.source_module.startswith(("noetrium_platform", "components", "orchestration", "noetrium"))
            ),
        )
        source_invariant_violations = audit_source_invariants(root)

    edges = profile.import_edges
    import_violations = tuple(
        ImportViolationRecord.from_violation(item)
        for item in audit_import_rules(edges, architecture_import_rules(root))
    )
    layer_violations = tuple(
        LayerViolationRecord.from_violation(item)
        for item in audit_layer_dag(root, edges)
    )
    cycles = package_cycles(edges)
    declared_authority_violations = build_platform_audit().run()
    hotspots = profile.hotspots[:hotspot_limit]
    risks = profile.optimization_risks[:hotspot_limit]
    source_authority_violations = profile.authority_violations
    architecture_complexity, architecture_complexity_budget, architecture_budget_violations = (
        audit_architecture_complexity_budget(
            root,
            import_edges=len(edges),
            import_edge_pairs=tuple(
                (edge.source_module, edge.target_module) for edge in edges
            ),
            source_index=source_index,
        )
    )
    declared_audit = build_platform_audit()
    capability_graph, operation_graph, event_graph = partition_seam_graphs(
        profile.seam_edges,
        declared_capabilities=declared_capability_graph(declared_audit),
    )
    system_graph = declared_system_graph()
    subsystem_graph = declared_subsystem_graph()

    draft = ArchitectureReport(
        source_root=str(root),
        source_digest=source_index.source_digest,
        import_edges=len(edges),
        import_violations=import_violations,
        layer_violations=layer_violations,
        package_cycles=cycles,
        declared_authority_violations=declared_authority_violations,
        source_invariant_violations=source_invariant_violations,
        source_authority_violations=source_authority_violations,
        architecture_complexity=architecture_complexity,
        architecture_complexity_budget=architecture_complexity_budget,
        architecture_budget_violations=architecture_budget_violations,
        top_hotspots=hotspots,
        top_optimization_risks=risks,
        capability_graph=capability_graph,
        operation_graph=operation_graph,
        event_graph=event_graph,
        system_graph=system_graph,
        subsystem_graph=subsystem_graph,
        report_sha256="",
    )
    identity = asdict(draft)
    identity.pop("source_root")
    identity.pop("report_sha256")
    return replace(draft, report_sha256=canonical_digest(identity))
