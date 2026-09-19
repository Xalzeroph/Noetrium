from __future__ import annotations
from collections import Counter
from noetrium_platform.foundation.governance.concurrency.api import ConcurrencySnapshot


def markdown_report(snapshot: ConcurrencySnapshot) -> str:
    lines=[
        "# Concurrency Governance Report", "",
        f"- Source digest: `{snapshot.source_digest}`",
        f"- Hotspots: **{len(snapshot.hotspots)}**",
        f"- Findings: **{snapshot.finding_count}**",
        f"- P0/P1 debt: **{snapshot.blocker_count}**", "",
        "## Coverage", "", "| Language | Files | Hotspots | Parse errors |", "|---|---:|---:|---:|",
    ]
    for row in snapshot.coverage:
        lines.append(f"| {row.language.value} | {row.file_count} | {row.hotspot_count} | {row.parse_errors} |")
    priority=Counter(); code=Counter()
    for hot in snapshot.hotspots:
        for finding in hot.findings:
            priority[finding.priority.value]+=1; code[finding.code]+=1
    lines += ["", "## Finding summary", "", "| Code | Count |", "|---|---:|"]
    for key,count in code.most_common(): lines.append(f"| `{key}` | {count} |")
    lines += ["", "## Hotspots", ""]
    for hot in snapshot.hotspots:
        if not hot.findings: continue
        lines.append(f"### `{hot.relative_path}::{hot.qualified_name}`")
        for finding in hot.findings:
            lines.append(f"- **{finding.priority.value}** `{finding.code}` line {finding.line}: {finding.detail}")
        lines.append("")
    return "\n".join(lines)+"\n"
