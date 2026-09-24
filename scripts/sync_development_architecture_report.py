#!/usr/bin/env python3
"""Synchronize the deterministic development architecture report projection."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.report import (
    ArchitectureReport,
    build_architecture_report,
)

REPORT_PATH = Path("DEVELOPMENT_ARCHITECTURE_REPORT.json")


def build_development_architecture_projection(
    root: Path,
) -> tuple[ArchitectureReport, dict[str, object]]:
    """Build one source-derived report with repository-independent path identity."""
    resolved = Path(root).resolve()
    report = build_architecture_report(resolved)
    document = asdict(report)
    # Absolute checkout paths are execution context, not architecture identity.
    document["source_root"] = "."
    return report, document


def projection_bytes(root: Path) -> bytes:
    _report, document = build_development_architecture_projection(root)
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sync(root: Path, *, check: bool) -> int:
    target = Path(root).resolve() / REPORT_PATH
    expected = projection_bytes(root)
    current = target.read_bytes() if target.is_file() else None
    if check:
        if current != expected:
            print(
                f"development architecture report drift: {REPORT_PATH.as_posix()}",
                file=sys.stderr,
            )
            return 1
        print("DEVELOPMENT_ARCHITECTURE_REPORT_CHECK_PASS")
        return 0
    if current != expected:
        target.write_bytes(expected)
        print("DEVELOPMENT_ARCHITECTURE_REPORT_SYNC_PASS changed=true")
    else:
        print("DEVELOPMENT_ARCHITECTURE_REPORT_SYNC_PASS changed=false")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize the canonical development architecture report."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    return sync(args.root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
