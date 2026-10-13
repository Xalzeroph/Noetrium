from __future__ import annotations

from pathlib import Path

from .source_scan import SourceInvariantViolation, imports, violation


def audit_quality_invariants(root: Path) -> list[SourceInvariantViolation]:
    quality = root / "noetrium_platform" / "foundation" / "governance" / "quality"
    rows: list[SourceInvariantViolation] = []
    aggregator = quality / "no_degradation.py"
    for module, line in imports(aggregator) if aggregator.exists() else ():
        if module in {"ast", "json", "tomllib", "re"}:
            rows.append(violation(root, aggregator, "no_degradation_aggregation_boundary", line, "no-degradation aggregator owns scanner implementation; keep AST/config parsing in dedicated scanners"))
    python_scan = quality / "degradation_python_scan.py"
    for module, line in imports(python_scan) if python_scan.exists() else ():
        if module in {"json", "tomllib"}:
            rows.append(violation(root, python_scan, "no_degradation_python_scanner_boundary", line, f"Python degradation scanner imports config parser {module}"))
    config_scan = quality / "degradation_config_scan.py"
    for module, line in imports(config_scan) if config_scan.exists() else ():
        if module == "ast":
            rows.append(violation(root, config_scan, "no_degradation_config_scanner_boundary", line, "config degradation scanner imports Python AST scanner authority"))
    return rows


__all__ = ["audit_quality_invariants"]
