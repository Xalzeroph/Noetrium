from __future__ import annotations

from collections import Counter, defaultdict

from noetrium_platform.foundation.governance.algorithm.api import AlgorithmSnapshot


def _system_for_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "noetrium_platform":
        return parts[1]
    if parts and parts[0] == "projects":
        return "projects"
    if parts and parts[0] in {"scripts", "deploy"}:
        return parts[0]
    return parts[0] if parts else "unknown"


def markdown_report(snapshot: AlgorithmSnapshot, *, hotspot_limit: int = 100) -> str:
    candidates = sorted(
        (row for row in snapshot.symbols if row.findings),
        key=lambda row: (-row.metrics.risk_score, row.symbol_id),
    )
    systems = Counter(_system_for_path(row.relative_path) for row in candidates)
    lines = [
        "# Algorithm Governance Report",
        "",
        f"- Source digest: `{snapshot.source_digest}`",
        f"- Analyzer revision: `{snapshot.analyzer_revision}`",
        f"- Symbols: **{len(snapshot.symbols)}**",
        f"- Optimization candidates: **{len(candidates)}**",
        "",
        "## Coverage",
        "",
        "| Language | Files | Symbols | Parse errors |",
        "|---|---:|---:|---:|",
    ]
    for row in snapshot.coverage:
        lines.append(f"| {row.language.value} | {row.file_count} | {row.symbol_count} | {row.parse_errors} |")
    lines.extend(["", "## Candidate debt by system", "", "| System | Candidates |", "|---|---:|"])
    for system, count in systems.most_common():
        lines.append(f"| {system} | {count} |")
    lines.extend(["", f"## Top {min(hotspot_limit, len(candidates))} hotspots", "", "| Score | Complexity | Symbol | Findings |", "|---:|---|---|---|"])
    for row in candidates[:hotspot_limit]:
        codes = ", ".join(f.code for f in row.findings)
        lines.append(f"| {row.metrics.risk_score} | {row.metrics.estimated_complexity} | `{row.symbol_id}` | {codes} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["markdown_report"]
