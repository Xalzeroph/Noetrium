from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.ownership_matrix import (
    build_ownership_matrix,
    load_catalog,
)
from noetrium_platform.foundation.kernel.kernel import (
    MachineConformanceHarness,
    MachineRuntime,
    NshCompiler,
    WorkerAdmission,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-unclassified", action="store_true")
    args = parser.parse_args()
    catalog_path = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    matrix_path = ROOT / "docs/architecture/OWNERSHIP_MATRIX.json"
    doc_path = ROOT / "docs/architecture/NOETRIUM_RESEARCH_OS_END_STATE_ARCHITECTURE.md"
    matrix = build_ownership_matrix(load_catalog(catalog_path))
    if not matrix_path.exists():
        raise SystemExit("ownership matrix is missing; run generate_ownership_matrix.py")
    stored = load_catalog(matrix_path)
    if stored.get("matrix_digest") != matrix.matrix_digest:
        raise SystemExit("ownership matrix digest drift; regenerate the derived matrix")
    if "## 52. R9" not in doc_path.read_text(encoding="utf-8"):
        raise SystemExit("architecture document is missing the final R9 gate")
    if args.strict_unclassified and any(row.audit_required for row in matrix.rows):
        raise SystemExit("ownership matrix contains explicitly unclassified fields")
    print({
        "systems": len(matrix.rows),
        "matrix_digest": matrix.matrix_digest,
        "unclassified_rows": sum(bool(row.audit_required) for row in matrix.rows),
        "kernel_exports": all((MachineRuntime, MachineConformanceHarness, NshCompiler, WorkerAdmission)),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
