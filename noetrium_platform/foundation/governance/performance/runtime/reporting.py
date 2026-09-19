from __future__ import annotations
from collections import Counter
from noetrium_platform.foundation.governance.performance.api import PerformanceSnapshot

def _system(path:str)->str:
    p=path.split('/')
    return p[1] if len(p)>1 and p[0]=='noetrium_platform' else (p[0] if p else 'unknown')

def markdown_report(snapshot: PerformanceSnapshot, *, limit:int=120)->str:
    rows=sorted(snapshot.hotspots,key=lambda x:(-x.metrics.risk_score,x.hotspot_id)); debt=Counter(_system(r.relative_path) for r in rows)
    lines=["# Performance Governance Report","",f"- Source digest: `{snapshot.source_digest}`",f"- Hotspots: **{len(rows)}**",f"- Findings: **{snapshot.finding_count}**",f"- P0/P1 blockers: **{snapshot.blocker_count}**","","## Coverage","","| Language | Files | Hotspots | Parse errors |","|---|---:|---:|---:|"]
    for c in snapshot.coverage: lines.append(f"| {c.language.value} | {c.file_count} | {c.hotspot_count} | {c.parse_errors} |")
    lines += ["","## Debt by system","","| System | Hotspots |","|---|---:|"]
    for k,v in debt.most_common(): lines.append(f"| {k} | {v} |")
    lines += ["",f"## Top {min(limit,len(rows))} hotspots","","| Score | Hotspot | Findings |","|---:|---|---|"]
    for r in rows[:limit]: lines.append(f"| {r.metrics.risk_score} | `{r.hotspot_id}` | {', '.join(f.code for f in r.findings)} |")
    lines.append(""); return "\n".join(lines)
