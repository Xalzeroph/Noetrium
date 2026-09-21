from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .runtime import audit_repository_boundary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the reusable upstream repository boundary.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--skip-release-manifest",
        action="store_true",
        help="audit live source boundaries without consulting a checked-in derived release manifest",
    )
    args = parser.parse_args(argv)
    report = audit_repository_boundary(
        Path(args.root), include_release_manifest=not args.skip_release_manifest
    )
    print(json.dumps({
        "schema": report.schema,
        "passed": report.passed,
        "violations": [asdict(row) for row in report.violations],
    }, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
