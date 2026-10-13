from __future__ import annotations

import argparse
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.project_root import discover_project_root
from .composition import build_performance_governance
from .runtime import PerformanceBaselineApprovalMissing, PerformanceBaselineMissing, markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repository-wide performance governance")
    parser.add_argument("command", choices=("scan", "gate", "baseline"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--git-executable", help="Git executable for immutable exact-source scans")
    parser.add_argument("--source-revision", help="historical Git revision to replay for baseline acceptance")
    args = parser.parse_args(argv)
    root = (args.root or discover_project_root(__file__)).resolve()
    service = build_performance_governance(
        root, exact=args.command in {"gate", "baseline"}, git_executable=args.git_executable
    )
    if args.command == "baseline":
        try:
            snapshot = service.accept_baseline(source_revision=args.source_revision)
        except PerformanceBaselineApprovalMissing as exc:
            print(f"PERFORMANCE_BASELINE_NOT_APPROVED {exc}")
            return 2
        print(
            "PERFORMANCE_BASELINE_ACCEPTED "
            f"hotspots={len(snapshot.hotspots)} blockers={snapshot.blocker_count}"
        )
    elif args.command == "gate":
        try:
            snapshot, report = service.gate()
        except PerformanceBaselineMissing as exc:
            print(f"PERFORMANCE_GATE_FAIL {exc}")
            return 2
        for blocker in report.blockers:
            print(f"BLOCKER {blocker}")
        for warning in report.warnings:
            print(f"WARNING {warning}")
        if not report.passed:
            return 1
        print(
            "PERFORMANCE_GATE_PASS "
            f"hotspots={len(snapshot.hotspots)} findings={snapshot.finding_count} debt={snapshot.blocker_count}"
        )
    else:
        snapshot = service.scan()
        print(
            "PERFORMANCE_SCAN_PASS "
            f"hotspots={len(snapshot.hotspots)} findings={snapshot.finding_count} debt={snapshot.blocker_count}"
        )
    if args.report:
        atomic_replace_bytes(args.report, markdown_report(snapshot).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
