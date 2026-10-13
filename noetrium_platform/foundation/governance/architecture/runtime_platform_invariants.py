from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def audit_runtime_platform_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    runtime = root / "noetrium_platform" / "research" / "execution" / "runtime" / "manager"
    control = runtime / "control_plane.py"
    platform = runtime / "platform_ports.py"

    for path in (control, platform):
        if not path.exists():
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in {"RuntimePlatformPorts", "ComposedRuntimePlatformPorts"}:
                rows.append(violation(
                    root, path, "runtime_platform_god_port_boundary", node.lineno,
                    f"runtime platform reintroduced monolithic forwarding interface {node.name}; compose narrow authorities instead",
                ))

    if platform.exists():
        tree = source_tree(platform)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "RuntimePlatformAuthorities":
                methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if methods:
                    rows.append(violation(
                        root, platform, "runtime_platform_authority_bundle_boundary", methods[0].lineno,
                        "RuntimePlatformAuthorities owns orchestration behavior; keep it as a data-only bundle of narrow ports",
                    ))
    return rows


__all__ = ["audit_runtime_platform_invariants"]
