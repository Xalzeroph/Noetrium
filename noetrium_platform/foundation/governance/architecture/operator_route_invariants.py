from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


_ROUTE_RULES = (
    (
        "audit/runtime/route_architecture.py",
        (
            "noetrium_platform.infrastructure.lifecycle.launch_control",
            "noetrium_platform.evidence.observability.telemetry",
            "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
            "noetrium_platform.foundation.governance.release.runtime",
        ),
    ),
    (
        "audit/runtime/route_release.py",
        (
            "noetrium_platform.infrastructure.lifecycle.launch_control",
            "noetrium_platform.evidence.observability.telemetry",
            "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
            "noetrium_platform.foundation.governance.architecture",
        ),
    ),
    (
        "query/runtime/route_runtime.py",
        (
            "noetrium_platform.foundation.governance.architecture",
            "noetrium_platform.evidence.observability.telemetry",
            "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
        ),
    ),
    (
        "query/runtime/route_telemetry.py",
        (
            "noetrium_platform.foundation.governance.architecture",
            "noetrium_platform.infrastructure.lifecycle.launch_control",
            "noetrium_platform.infrastructure.reliability.diagnostics.runtime",
            "noetrium_platform.foundation.governance.release.runtime",
        ),
    ),
)


def audit_operator_route_invariants(root: Path) -> list[SourceInvariantViolation]:
    operator = root / "noetrium_platform" / "product" / "operator"
    rows: list[SourceInvariantViolation] = []

    for path in sorted(operator.glob("*.py")) if operator.exists() else ():
        if path.name != "__init__.py":
            rows.append(violation(
                root,
                path,
                "operator_layer_layout",
                1,
                f"operator implementation module {path.name} is flat at system root; use runtime or a child operator authority",
            ))

    legacy = operator / "routes.py"
    if legacy.exists():
        rows.append(violation(
            root, legacy, "operator_route_family_boundary", 1,
            "operator command families reintroduced in one monolithic routes.py; keep route handlers independent",
        ))

    for relative, forbidden in _ROUTE_RULES:
        path = operator / relative
        if not path.exists():
            continue
        for module, line in imports(path):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden):
                rows.append(violation(
                    root, path, "operator_route_family_boundary", line,
                    f"operator route family imports unrelated system {module}",
                ))
    return rows


__all__ = ["audit_operator_route_invariants"]
