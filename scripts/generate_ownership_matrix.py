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
    write_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/architecture/OWNERSHIP_MATRIX.json",
    )
    args = parser.parse_args()
    matrix = build_ownership_matrix(load_catalog(args.catalog))
    write_matrix(matrix, args.output)
    print(matrix.matrix_digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
