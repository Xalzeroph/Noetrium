"""Source-level guardrails for typed composition plans.

The capability graph is evidence produced at composition time, never a runtime
container.  These checks keep that distinction enforceable as new systems and
projects are added.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_text, source_tree

from .source_scan import SourceInvariantViolation, violation


_GRAPH_MODULE = "noetrium_platform.foundation.governance.architecture.runtime.capability_composition"
_HOST_PROVIDER_MODULE = "noetrium_platform.infrastructure.lifecycle.host.providers"
_PLAN_FORBIDDEN_METHODS = frozenset({"get", "resolve", "lookup", "locate"})


def _is_composition_module(path: Path) -> bool:
    return "composition" in path.parts


def audit_capability_composition_boundaries(root: Path) -> list[SourceInvariantViolation]:
    """Reject runtime service-location and bypassed host construction."""

    rows: list[SourceInvariantViolation] = []
    package = root / "noetrium_platform"
    if not package.exists():
        return rows
    for path in sorted(package.rglob("*.py")):
        text = source_text(path)
        if _GRAPH_MODULE not in text and _HOST_PROVIDER_MODULE not in text and "BindingPlan" not in text:
            continue
        tree = source_tree(path)
        is_composition = _is_composition_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == _GRAPH_MODULE and not is_composition:
                    rows.append(
                        violation(
                            root,
                            path,
                            "capability_graph_runtime_firewall",
                            node.lineno,
                            "only a composition module may import typed capability graph metadata",
                        )
                    )
                if (
                    module == _HOST_PROVIDER_MODULE
                    and not path.as_posix().endswith("runtime/host/composition/authorities.py")
                ):
                    if any(alias.name == "LocalOperatingSystemRoute" for alias in node.names):
                        rows.append(
                            violation(
                                root,
                                path,
                                "host_route_composition_boundary",
                                node.lineno,
                                "only runtime/host composition may select LocalOperatingSystemRoute",
                            )
                        )
            elif isinstance(node, ast.ClassDef) and node.name == "BindingPlan":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in _PLAN_FORBIDDEN_METHODS:
                        rows.append(
                            violation(
                                root,
                                path,
                                "binding_plan_service_locator_forbidden",
                                item.lineno,
                                f"BindingPlan cannot expose runtime lookup method {item.name}",
                            )
                        )
    return rows


__all__ = ["audit_capability_composition_boundaries"]
