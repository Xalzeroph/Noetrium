#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.finalization import (
    build_finalization_report,
    render_finalization_markdown,
    write_finalization_artifacts,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noetrium audit-finalization",
        description="Audit canonical graph/authority/provider finalization.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".noetrium" / "finalization-audit",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="also run the complete architecture release gate",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit compact JSON summary instead of Markdown",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="always exit zero after generating the report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_finalization_report(ROOT, full=args.full)
    report_path, suspects_path, spine_path = write_finalization_artifacts(
        report,
        args.output,
    )
    if args.json:
        print(json.dumps({
            "clean": report.clean,
            "finalization_score": report.finalization_score,
            "issue_counts": dict(report.issue_counts),
            "classification_counts": dict(report.classification_counts),
            "report": str(report_path),
            "suspects": str(suspects_path),
            "spine": str(spine_path),
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(render_finalization_markdown(report), end="")
        print(f"report={report_path}")
        print(f"suspects={suspects_path}")
        print(f"spine={spine_path}")
    if args.no_fail:
        return 0
    return 0 if report.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
