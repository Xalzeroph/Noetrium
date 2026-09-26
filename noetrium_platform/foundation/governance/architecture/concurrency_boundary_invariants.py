from __future__ import annotations

import ast
from pathlib import Path

from .import_graph import scan_imports
from .source_index import source_tree
from .source_scan import SourceInvariantViolation, is_transient_source_path, violation


_CONCURRENCY_MODULE_PREFIX = "noetrium_platform.foundation.kernel.concurrency"
_POLICY_MODULE_PREFIX = "noetrium_platform.research.execution.policy"
_POLICY_SCHEDULING_PREFIX = "noetrium_platform.research.execution.policy.scheduling"
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
    """Enforce neutral concurrency mechanism below the unified execution-policy context."""

    rows: list[SourceInvariantViolation] = []
    for edge in scan_imports(root, package_roots=("noetrium_platform", "projects", "scripts")):
        source = edge.source_module
        target = edge.target_module

        if source == _CONCURRENCY_MODULE_PREFIX or source.startswith(_CONCURRENCY_MODULE_PREFIX + "."):
            if target == _POLICY_MODULE_PREFIX or target.startswith(_POLICY_MODULE_PREFIX + "."):
                rows.append(
                    violation(
                        root,
                        root / edge.path,
                        "concurrency_policy_dependency_inversion",
                        edge.line,
                        (
                            f"platform/concurrency may not import execution policy {target}; "
                            "inject a neutral public concurrency Port from composition"
                        ),
                    )
                )

        # Scheduling is an internal pure ordering facet.  It may depend on its own
        # API and kernel values, but never on admission/runtime state from the
        # enclosing policy context.
        if source == _POLICY_SCHEDULING_PREFIX or source.startswith(_POLICY_SCHEDULING_PREFIX + "."):
            if (
                target == _POLICY_MODULE_PREFIX
                or (
                    target.startswith(_POLICY_MODULE_PREFIX + ".")
                    and not target.startswith(_POLICY_SCHEDULING_PREFIX + ".")
                )
            ):
                rows.append(
                    violation(
                        root,
                        root / edge.path,
                        "policy_scheduling_state_dependency",
                        edge.line,
                        f"execution/policy scheduling facet must remain state-free: {target}",
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
