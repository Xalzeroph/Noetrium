from __future__ import annotations

import ast
from pathlib import Path

from .import_graph import scan_imports
from .source_index import source_tree
from .source_scan import SourceInvariantViolation, is_transient_source_path, violation


_CONCURRENCY_MODULE_PREFIX = "noetrium_platform.foundation.kernel.concurrency"
_ADMISSION_MODULE_PREFIX = "noetrium_platform.research.execution.admission"
_SCHEDULING_MODULE_PREFIX = "noetrium_platform.research.execution.scheduling"
_FORBIDDEN_DIRECT_MODULES = frozenset(
    {
        "noetrium_platform.foundation.kernel.concurrency.providers",
        "noetrium_platform.foundation.kernel.concurrency.runtime",
        "noetrium_platform.foundation.kernel.concurrency.api.ports",
    }
)
_LEGACY_EXECUTION_METHODS = frozenset(
    {
        "submit_blocking",
        "submit_cpu",
        "submit_serial",
        "schedule_serial_fixed_delay",
    }
)
_CONCURRENCY_FORBIDDEN_POLICY_IDENTIFIERS = frozenset(
    {
        "AdmissionBudget",
        "AdmissionIdentity",
        "AdmissionIntent",
        "AdmissionMode",
        "AdmissionRejected",
        "ExecutionPriority",
        "SchedulingCandidate",
        "FairPrioritySchedulingPolicy",
        "priority_aging_seconds",
        "tenant_id",
        "resource_id",
        "group_last_grant",
    }
)


def _is_forbidden_target(module: str) -> bool:
    head = module.rsplit(".", 1)[0]
    return module in _FORBIDDEN_DIRECT_MODULES or head in _FORBIDDEN_DIRECT_MODULES or any(
        module.startswith(prefix + ".") for prefix in _FORBIDDEN_DIRECT_MODULES
    )


def _audit_legacy_execution_seams(root: Path) -> list[SourceInvariantViolation]:
    """Scan each Python source/AST node once for forbidden legacy execution calls.

    Algorithm-Complexity: O(N)
    Algorithm-Rationale: N is the total Python source plus AST nodes; package roots,
    files, and AST nodes are disjoint repository partitions rather than multiplicative
    input dimensions.
    """

    rows: list[SourceInvariantViolation] = []
    for package_root in (root / "noetrium_platform", root / "projects", root / "scripts"):
        if not package_root.exists():
            continue
        for path in sorted(package_root.rglob("*.py")):
            if is_transient_source_path(path):
                continue
            relative = path.relative_to(root).as_posix()
            if relative.startswith("noetrium_platform/foundation/kernel/concurrency/"):
                continue
            tree = source_tree(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in _LEGACY_EXECUTION_METHODS:
                    continue
                rows.append(
                    violation(
                        root,
                        path,
                        "legacy_concurrency_execution_seam",
                        getattr(node, "lineno", 0),
                        (
                            f"legacy execution method .{node.func.attr}() bypasses the unified "
                            "ExecutorPort.submit(ExecutionSpec, ...) or runtime heartbeat scheduler"
                        ),
                    )
                )
    return rows


def _audit_policy_dependency_direction(root: Path) -> list[SourceInvariantViolation]:
    """Enforce scheduling -> admission -> neutral permit -> concurrency layering."""

    rows: list[SourceInvariantViolation] = []
    for edge in scan_imports(root, package_roots=("noetrium_platform", "projects", "scripts")):
        source = edge.source_module
        target = edge.target_module

        if source == _CONCURRENCY_MODULE_PREFIX or source.startswith(_CONCURRENCY_MODULE_PREFIX + "."):
            if target == _ADMISSION_MODULE_PREFIX or target.startswith(_ADMISSION_MODULE_PREFIX + ".") or target == _SCHEDULING_MODULE_PREFIX or target.startswith(_SCHEDULING_MODULE_PREFIX + "."):
                rows.append(
                    violation(
                        root,
                        root / edge.path,
                        "concurrency_policy_dependency_inversion",
                        edge.line,
                        (
                            f"platform/concurrency may not import policy system {target}; "
                            "inject a neutral public concurrency Port from composition"
                        ),
                    )
                )

        if source == _ADMISSION_MODULE_PREFIX or source.startswith(_ADMISSION_MODULE_PREFIX + "."):
            if target.startswith(_SCHEDULING_MODULE_PREFIX + ".") and not target.startswith(
                _SCHEDULING_MODULE_PREFIX + ".api"
            ):
                rows.append(
                    violation(
                        root,
                        root / edge.path,
                        "admission_scheduling_implementation_bypass",
                        edge.line,
                        f"execution/admission may consume scheduling only through public API, not {target}",
                    )
                )

        if source == _SCHEDULING_MODULE_PREFIX or source.startswith(_SCHEDULING_MODULE_PREFIX + "."):
            if target == _ADMISSION_MODULE_PREFIX or target.startswith(_ADMISSION_MODULE_PREFIX + "."):
                rows.append(
                    violation(
                        root,
                        root / edge.path,
                        "scheduling_admission_reverse_dependency",
                        edge.line,
                        f"execution/scheduling may not depend on execution/admission: {target}",
                    )
                )
    return rows


def _audit_concurrency_policy_ownership(root: Path) -> list[SourceInvariantViolation]:
    """Prevent admission/scheduling/resource identity semantics from drifting into mechanism code."""

    rows: list[SourceInvariantViolation] = []
    package = root / "noetrium_platform" / "foundation" / "kernel" / "concurrency"
    if not package.exists():
        return rows
    for path in sorted(package.rglob("*.py")):
        if is_transient_source_path(path):
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            identifier: str | None = None
            if isinstance(node, ast.Name):
                identifier = node.id
            elif isinstance(node, ast.arg):
                identifier = node.arg
            if identifier not in _CONCURRENCY_FORBIDDEN_POLICY_IDENTIFIERS:
                continue
            rows.append(
                violation(
                    root,
                    path,
                    "concurrency_policy_ownership_violation",
                    getattr(node, "lineno", 0),
                    f"platform/concurrency must not own execution-policy identifier: {identifier}",
                )
            )
    return rows


def audit_concurrency_boundary_invariants(root: Path) -> list[SourceInvariantViolation]:
    """Keep concurrency mechanism and execution policy in separate authorities."""

    root = Path(root).resolve()
    rows: list[SourceInvariantViolation] = []
    for edge in scan_imports(root, package_roots=("noetrium_platform", "projects", "scripts")):
        if edge.source_module == _CONCURRENCY_MODULE_PREFIX or edge.source_module.startswith(
            _CONCURRENCY_MODULE_PREFIX + "."
        ):
            continue
        if not _is_forbidden_target(edge.target_module):
            continue
        rows.append(
            violation(
                root,
                root / edge.path,
                "structured_concurrency_provider_firewall",
                edge.line,
                (
                    f"direct concurrency implementation import {edge.target_module}; "
                    "depend on noetrium_platform.foundation.kernel.concurrency.api and obtain task groups from composition"
                ),
            )
        )
    rows.extend(_audit_legacy_execution_seams(root))
    rows.extend(_audit_policy_dependency_direction(root))
    rows.extend(_audit_concurrency_policy_ownership(root))
    return rows


__all__ = ["audit_concurrency_boundary_invariants"]
