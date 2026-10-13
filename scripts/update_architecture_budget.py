#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.budget import (
    architecture_baseline_digest,
    source_catalog_complexity,
)
from noetrium_platform.foundation.governance.architecture.source_authority import (
    architecture_source_authority_rules,
)
from noetrium_platform.foundation.governance.architecture.source_profile import (
    scan_architecture_source_profile,
)
from noetrium_platform.foundation.governance.providers import RepositorySourceTree

BUDGET_PATH = ROOT / "noetrium_platform/foundation/governance/architecture/ARCHITECTURE_BUDGET.json"


def main() -> int:
    source_index = RepositorySourceTree(ROOT).index()
    profile = scan_architecture_source_profile(
        ROOT,
        source_index=source_index,
        authority_rules=architecture_source_authority_rules(ROOT),
    )
    pairs = tuple((edge.source_module, edge.target_module) for edge in profile.import_edges)
    complexity = source_catalog_complexity(source_index, import_edges=len(profile.import_edges))
    document = {
        "schema_version": "noetrium.architecture-budget.v1",
        "architecture_digest": architecture_baseline_digest(complexity, import_edge_pairs=pairs),
        "limits": {
            "top_level_systems": complexity.top_level_systems,
            "subsystems": complexity.subsystems,
            "contract_declarations": complexity.contract_declarations,
            "authorities": complexity.authorities,
            "import_edges": complexity.import_edges,
        },
    }
    BUDGET_PATH.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "ARCHITECTURE_BUDGET_UPDATED "
        f"digest={document['architecture_digest']} import_edges={complexity.import_edges}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
