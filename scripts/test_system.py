"""Canonical test-system inventory and gate runner.

The existing top-level test files remain compatibility artifacts. This module
gives every file a stable taxonomy identity and makes gate selection explicit.
It intentionally does not infer scientific readiness from a passing local gate.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "tests" / "TEST_SYSTEM.json"


class TestSystemError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TestFileClassification:
    path: str
    rule_id: str
    family: str
    level: str
    risk: str
    gates: tuple[str, ...]
    intent: str
    parallelism: str


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TestSystemError(f"cannot load test catalog: {path}") from exc
    if value.get("schema_version") != 1:
        raise TestSystemError("unsupported test catalog schema")
    return value


def test_files(root: Path = ROOT) -> tuple[Path, ...]:
    return tuple(sorted((root / "tests").glob("test_*.py")))


def classify(path: Path, catalog: dict[str, Any], root: Path = ROOT) -> TestFileClassification:
    name = path.name
    matches = [rule for rule in catalog["rules"] if re.search(rule["pattern"], name)]
    if len(matches) != 1:
        detail = "none" if not matches else ", ".join(rule["id"] for rule in matches)
        raise TestSystemError(f"{name}: expected exactly one taxonomy rule, matched {detail}")
    rule = matches[0]
    family = rule["family"]
    family_data = catalog["families"].get(family)
    if family_data is None:
        raise TestSystemError(f"{name}: rule references unknown family {family}")
    gates = tuple(gate_id for gate_id, gate in catalog["gates"].items() if family in gate["families"])
    return TestFileClassification(
        path=str(path.relative_to(root).as_posix()),
        rule_id=rule["id"],
        family=family,
        level=family_data["level"],
        risk=family_data["risk"],
        gates=gates,
        intent=family_data["intent"],
        parallelism=str(family_data.get("parallelism", "exclusive")),
    )


def inventory(root: Path = ROOT) -> tuple[TestFileClassification, ...]:
    catalog = load_catalog(root / "tests" / "TEST_SYSTEM.json")
    rows = tuple(classify(path, catalog, root) for path in test_files(root))
    if len({row.path for row in rows}) != len(rows):
        raise TestSystemError("test inventory contains duplicate paths")
    return rows


def _collect_count(root: Path) -> int:
    process = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        raise TestSystemError(process.stderr.strip() or process.stdout.strip() or "pytest collection failed")
    matches = re.findall(r"(\d+) tests? collected", process.stdout)
    if not matches:
        raise TestSystemError("pytest collection count was not found")
    return int(matches[-1])


def check(root: Path = ROOT) -> tuple[TestFileClassification, ...]:
    rows = inventory(root)
    catalog = load_catalog(root / "tests" / "TEST_SYSTEM.json")
    known_families = set(catalog["families"])
    for row in rows:
        if row.family not in known_families or not row.gates:
            raise TestSystemError(f"{row.path}: classification has no valid gate")
        if row.parallelism not in {"parallel-safe", "process-isolated", "exclusive"}:
            raise TestSystemError(f"{row.path}: unsupported parallelism class {row.parallelism}")
    return rows


def _summary(rows: tuple[TestFileClassification, ...]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = result.setdefault(row.family, {"files": 0, "P0": 0})
        bucket["files"] += 1
        bucket[row.risk] = bucket.get(row.risk, 0) + 1
    return result


def _run_gate(gate: str, rows: tuple[TestFileClassification, ...], root: Path) -> int:
    if gate == "live":
        print("TEST_SYSTEM_LIVE_GATE_EXTERNAL_REQUIRED qualified deployment and live evidence are required")
        return 3
    selected = tuple(row.path for row in rows if gate in row.gates)
    if not selected:
        raise TestSystemError(f"gate has no test files: {gate}")
    command = [sys.executable, "-m", "pytest", "-q", *selected]
    print(f"TEST_SYSTEM_GATE_START gate={gate} files={len(selected)}", flush=True)
    return subprocess.run(command, cwd=root, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("inventory")
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--json", action="store_true", dest="as_json")
    explain_parser = sub.add_parser("explain")
    explain_parser.add_argument("path")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("gate", choices=tuple(load_catalog()["gates"]))
    args = parser.parse_args(argv)
    try:
        rows = check()
        if args.command == "check":
            print(f"TEST_SYSTEM_CHECK_PASS files={len(rows)}")
        elif args.command == "inventory":
            print(json.dumps({"file_count": len(rows), "pytest_test_count": _collect_count(ROOT), "summary": _summary(rows)}, ensure_ascii=False, indent=2))
        elif args.command == "list":
            if args.as_json:
                print(json.dumps({"files": [asdict(row) for row in rows], "summary": _summary(rows)}, ensure_ascii=False, indent=2))
            else:
                for family, counts in sorted(_summary(rows).items()):
                    print(f"{family}\t{counts['files']} files\t{counts.get('P0', 0)} P0")
        elif args.command == "explain":
            match = next((row for row in rows if row.path == args.path or Path(row.path).name == args.path), None)
            if match is None:
                raise TestSystemError(f"test file is not in inventory: {args.path}")
            print(json.dumps({"path": match.path, "rule_id": match.rule_id, "family": match.family, "level": match.level, "risk": match.risk, "gates": match.gates, "intent": match.intent, "parallelism": match.parallelism}, ensure_ascii=False, indent=2))
        else:
            return _run_gate(args.gate, rows, ROOT)
    except TestSystemError as exc:
        print(f"TEST_SYSTEM_FAIL {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
