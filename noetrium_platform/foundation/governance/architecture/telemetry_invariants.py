from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def _audit_layer_firewall(root: Path, subsystem: Path, label: str) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    api = subsystem / "api"
    runtime = subsystem / "runtime"
    providers = subsystem / "providers"
    composition = subsystem / "composition"
    package = ".".join(subsystem.relative_to(root).parts)

    forbidden_by_layer = (
        (api, (f"{package}.runtime", f"{package}.providers", f"{package}.composition"), f"{label}_api_dependency_direction"),
        (runtime, (f"{package}.providers", f"{package}.composition"), f"{label}_runtime_dependency_direction"),
        (providers, (f"{package}.runtime", f"{package}.composition"), f"{label}_provider_dependency_direction"),
    )
    for base, forbidden, invariant in forbidden_by_layer:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith(forbidden):
                    rows.append(violation(
                        root, path, invariant, line,
                        f"{label} layer imports upward/concrete layer {module}; depend on API ports and wire in composition",
                    ))
    return rows


def _audit_flat_layout(root: Path, subsystem: Path, label: str) -> list[SourceInvariantViolation]:
    if not subsystem.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    for path in sorted(subsystem.glob("*.py")):
        if path.name != "__init__.py":
            rows.append(violation(
                root, path, f"{label}_layer_layout", 1,
                f"{label} implementation module {path.name} is flat at subsystem root; use api/runtime/providers/composition",
            ))
    return rows


def audit_telemetry_invariants(root: Path) -> list[SourceInvariantViolation]:
    telemetry = root / "noetrium_platform" / "evidence" / "observability" / "telemetry"
    metric = telemetry / "metric"
    event = telemetry / "event"
    capture = root / "noetrium_platform" / "evidence" / "observability" / "capture"
    rows: list[SourceInvariantViolation] = []

    rows.extend(_audit_flat_layout(root, metric, "telemetry_metric"))
    rows.extend(_audit_flat_layout(root, event, "telemetry_event"))
    rows.extend(_audit_flat_layout(root, capture, "observability_capture"))
    rows.extend(_audit_layer_firewall(root, metric, "telemetry_metric"))
    rows.extend(_audit_layer_firewall(root, event, "telemetry_event"))
    rows.extend(_audit_layer_firewall(root, capture, "observability_capture"))

    store = metric / "runtime" / "store.py"
    if store.exists():
        tree = source_tree(store)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "backend" and isinstance(node.ctx, ast.Load):
                rows.append(violation(
                    root, store, "telemetry_backend_encapsulation", node.lineno,
                    "TelemetryStore exposes/reaches backend through public .backend; keep persistence private",
                ))

    batch = metric / "runtime" / "batch.py"
    if batch.exists():
        tree = source_tree(batch)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_") and isinstance(node.value, ast.Attribute):
                if node.value.attr in {"store", "_session"}:
                    rows.append(violation(
                        root, batch, "telemetry_private_object_graph_boundary", node.lineno,
                        "telemetry batch path reaches private collaborator internals; widen the explicit port instead",
                    ))
    return rows


__all__ = ["audit_telemetry_invariants"]
