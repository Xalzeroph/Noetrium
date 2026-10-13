#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.system_dependency_invariants import (
    layer_dependency_findings,
)



def main() -> int:
    findings = layer_dependency_findings(ROOT)
    counts = Counter(row.kind for row in findings)
    edges = sorted({
        (row.source_layer, row.target_layer)
        for row in findings
        if row.source_layer is not None and row.target_layer is not None
    })
    result = {
        "schema": "noetrium-layer-dependency-audit.v3",
        "violation_count": len(findings),
        "violation_kind_counts": dict(sorted(counts.items())),
        "layer_edge_count": len(edges),
        "layer_edges": [list(row) for row in edges],
        "violations": [asdict(row) for row in findings],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
