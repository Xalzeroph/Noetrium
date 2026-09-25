from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
TARGET = ROOT / "docs/architecture/AUTHORITY_DISPOSITION_MATRIX_20260916.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.authority_disposition import (
    build_authority_disposition_matrix,
)


def render(root: Path) -> bytes:
    catalog_path = root / CATALOG.relative_to(ROOT)
    document = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document:
        raise ValueError("canonical system registry must be a non-empty object")
    rows = build_authority_disposition_matrix(document)
    payload = [row.as_dict() for row in rows]
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def generate(root: Path, *, check: bool) -> int:
    target = root / TARGET.relative_to(ROOT)
    expected = render(root)
    actual = target.read_bytes() if target.is_file() else None
    if check:
        if actual != expected:
            print("authority disposition matrix drift")
            return 1
        print("AUTHORITY_DISPOSITION_MATRIX_CHECK_PASS")
        return 0
    if actual != expected:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected)
        print(f"wrote {target.relative_to(root)}")
    else:
        print("authority disposition matrix already current")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the authority disposition matrix from the canonical system registry."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    return generate(args.root.resolve(), check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
