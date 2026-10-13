"""Executable fitness functions for architecture-wide ownership boundaries.

Keep ownership rules close to the canonical architecture gate. These checks do
not prescribe a specific scheduling algorithm: they require the implementation
to enter each model domain through one explicitly injected Port.
"""
from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree
from .source_scan import SourceInvariantViolation, violation


_REQUIRED_MODEL_PORTS = {
    "noetrium_platform/composition/concurrency.py": (
        None, "build_execution_concurrency_runtime"
    ),
    "noetrium_platform/capabilities/model/serving/endpoint/runtime/replica_pool.py": (
        "AdaptiveModelEndpointPool", "__init__"
    ),
    "noetrium_platform/capabilities/model/serving/endpoint/composition/qualified.py": (
        None, "build_adaptive_model_endpoint_pool"
    ),
    "noetrium_platform/capabilities/model/serving/endpoint/composition/runtime_canary.py": (
        None, "build_runtime_canary_endpoint"
    ),
    "noetrium_platform/capabilities/model/serving/composition/qualification_closure.py": (
        None, "qualify_and_publish_model_deployment_closure"
    ),
}

_REQUIRED_ROOT_BINDINGS = {
    "noetrium_platform/composition/operator/query/route_runtime.py": "build_execution_concurrency_runtime",
    "noetrium_platform/composition/operator/wiring/research.py": "build_execution_concurrency_runtime",
    "noetrium_platform/composition/release_quality.py": "build_execution_concurrency_runtime",
    "noetrium_platform/composition/research_execution_pool.py": "build_adaptive_model_endpoint_pool",
    "noetrium_platform/composition/model_runtime_bootstrap.py": "qualify_and_publish_model_deployment_closure",
    "noetrium_platform/composition/model_runtime_refresh.py": "qualify_and_publish_model_deployment_closure",
    "noetrium_platform/capabilities/model/serving/endpoint/composition/runtime_canary.py": "AdaptiveModelEndpointPool",
    "noetrium_platform/capabilities/model/serving/endpoint/composition/qualified.py": "AdaptiveModelEndpointPool",
    "noetrium_platform/capabilities/model/serving/composition/qualification_closure.py": "build_runtime_canary_endpoint",
}


def _method(tree: ast.Module, owner: str | None, name: str):
    body = tree.body
    if owner is not None:
        classes = [row for row in body if isinstance(row, ast.ClassDef) and row.name == owner]
        if not classes:
            return None
        body = classes[0].body
    return next((row for row in body if isinstance(row, (ast.FunctionDef, ast.AsyncFunctionDef)) and row.name == name), None)


def audit_engineering_pattern_invariants(root: Path) -> list[SourceInvariantViolation]:
    root = Path(root).resolve()
    if not (root / "noetrium_platform").exists():
        return []
    rows: list[SourceInvariantViolation] = []
    # All physical scheduling state construction belongs to exactly one
    # composition factory; any other production constructor splits service
    # accounting and may silently violate fairness across model pools.
    scheduler_runtime_module = "noetrium_platform.foundation.kernel.concurrency.scheduling.runtime"
    for path in sorted((root / "noetrium_platform").rglob("*.py")):
        relative_path = path.relative_to(root).as_posix()
        if relative_path.startswith("noetrium_platform/foundation/"):
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == scheduler_runtime_module
                and relative_path != "noetrium_platform/composition/concurrency.py"
            ):
                rows.append(violation(root, path, "single_scheduler_constructor", node.lineno, "only application scheduler factory may depend on concrete scheduler runtime"))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "UnifiedSchedulingAuthority"
                and relative_path != "noetrium_platform/composition/concurrency.py"
            ):
                rows.append(violation(root, path, "single_scheduler_constructor", node.lineno, "scheduler must be constructed at one application composition factory"))
    for relative, (owner, name) in _REQUIRED_MODEL_PORTS.items():
        path = root / relative
        if not path.is_file():
            continue
        tree = source_tree(path)
        method = _method(tree, owner, name)
        if method is None:
            rows.append(violation(root, path, "model_scheduler_composition", 1, f"model scheduling entry {name} is missing"))
            continue
        params = method.args.kwonlyargs
        defaults = method.args.kw_defaults
        port = next(((arg, default) for arg, default in zip(params, defaults, strict=True) if arg.arg == "scheduling_authority"), None)
        if port is None or port[1] is not None:
            rows.append(violation(root, path, "model_scheduler_composition", method.lineno, f"{name} must require an explicitly injected scheduling_authority Port"))
        if relative.endswith("runtime/replica_pool.py"):
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "noetrium_platform.foundation.kernel.concurrency.scheduling.runtime":
                    rows.append(violation(root, path, "model_scheduler_concrete_dependency", node.lineno, "model runtime cannot construct the concrete scheduling authority"))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "UnifiedSchedulingAuthority":
                    rows.append(violation(root, path, "model_scheduler_concrete_dependency", node.lineno, "model runtime may not create an independent scheduling state"))
    for relative, callee in _REQUIRED_ROOT_BINDINGS.items():
        path = root / relative
        if not path.is_file():
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != callee:
                continue
            if not any(keyword.arg == "scheduling_authority" for keyword in node.keywords):
                rows.append(violation(root, path, "model_scheduler_composition", node.lineno, f"{callee} must receive owning scheduling_authority"))
    return rows


__all__ = ["audit_engineering_pattern_invariants"]
