from __future__ import annotations

import argparse
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.project_root import discover_project_root
from .composition import build_algorithm_governance
from .runtime import AlgorithmBaselineApprovalMissing, AlgorithmBaselineMissing, markdown_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repository-wide algorithm governance")
    parser.add_argument("command", choices=("scan", "gate", "baseline"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--exact", action="store_true", help="disable advisory cache")
    parser.add_argument("--report", type=Path, help="write Markdown report")
    parser.add_argument("--git-executable", help="Git executable for immutable exact-source scans")
    parser.add_argument("--source-revision", help="historical Git revision to replay for baseline acceptance")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = (args.root or discover_project_root(__file__)).resolve()
    # Gate and baseline are always exact; cache is advisory only.
    exact = bool(args.exact or args.command in {"gate", "baseline"})
    service = build_algorithm_governance(root, exact=exact, git_executable=args.git_executable)
    if args.command == "baseline":
        try:
            snapshot = service.accept_baseline(source_revision=args.source_revision)
        except AlgorithmBaselineApprovalMissing as exc:
            print(f"ALGORITHM_BASELINE_NOT_APPROVED {exc}")
            return 2
        print(f"ALGORITHM_BASELINE_ACCEPTED symbols={len(snapshot.symbols)} candidates={snapshot.candidate_count}")
    elif args.command == "gate":
        try:
            snapshot, report = service.gate()
        except AlgorithmBaselineMissing as exc:
            print(f"ALGORITHM_GATE_FAIL {exc}")
            return 2
        for blocker in report.blockers:
            print(f"BLOCKER {blocker}")
        for warning in report.warnings:
            print(f"WARNING {warning}")
        if not report.passed:
            return 1
        print(f"ALGORITHM_GATE_PASS symbols={len(snapshot.symbols)} candidates={snapshot.candidate_count}")
    else:
        snapshot = service.scan()
        print(f"ALGORITHM_SCAN_PASS symbols={len(snapshot.symbols)} candidates={snapshot.candidate_count}")
    if args.report:
        atomic_replace_bytes(args.report, markdown_report(snapshot).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
