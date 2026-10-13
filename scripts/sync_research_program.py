from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

CONTROL_SCHEMA = "noetrium.research-program-control.v1"
BENCHMARK_CATALOG_SCHEMA = "noetrium.benchmark-catalog.projection.v2"
REPRODUCTION_CATALOG_SCHEMA = "noetrium.reproduction-catalog.projection.v1"
PROGRAM_SCHEMA = "noetrium.research-program.projection.v3"
PROGRAM_AUTHORITY = "generated_from_program_control_benchmark_catalog_and_reproduction_catalog"


def _load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _ids(rows: object, field: str, label: str) -> set[str]:
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise TypeError(f"{label} must be a list of objects")
    values = [row.get(field) for row in rows]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{label} requires non-empty {field}")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate {field}")
    return set(values)


def project(root: Path) -> Mapping[str, Any]:
    control = _load(root / "research/catalog/research_program_control.json")
    benchmarks = _load(root / "research/catalog/benchmark_catalog.json")
    reproductions = _load(root / "research/catalog/reproduction_catalog.json")

    if control.get("schema") != CONTROL_SCHEMA:
        raise ValueError(f"research_program_control.json must use {CONTROL_SCHEMA}")
    if benchmarks.get("schema") != BENCHMARK_CATALOG_SCHEMA or benchmarks.get("authority") != "generated_from_benchmark_manifests":
        raise ValueError("benchmark_catalog.json is not the canonical benchmark projection")
    if reproductions.get("schema") != REPRODUCTION_CATALOG_SCHEMA or reproductions.get("authority") != "generated_from_typed_reproduction_definitions":
        raise ValueError("reproduction_catalog.json is not the canonical reproduction projection")

    benchmark_rows = benchmarks.get("benchmarks")
    method_rows = reproductions.get("methods")
    benchmark_ids = _ids(benchmark_rows, "benchmark_id", "benchmark catalog")
    method_ids = _ids(method_rows, "method_id", "reproduction catalog")

    for row in method_rows:
        packages = row.get("reproduction_packages")
        if not isinstance(packages, list) or not packages:
            raise ValueError(f"active method {row['method_id']} has no typed reproduction package")
        refs = row.get("benchmark_ids", [])
        if not isinstance(refs, list) or any(ref not in benchmark_ids for ref in refs):
            raise ValueError(f"active method {row['method_id']} references an unknown benchmark")

    gaps = control.get("platform_gaps")
    innovations = control.get("innovation_tracks")
    constraints = control.get("project_constraints")
    _ids(gaps, "gap_id", "platform gaps")
    innovation_ids = _ids(innovations, "innovation_id", "innovation tracks")
    if not isinstance(constraints, list) or any(not isinstance(row, Mapping) for row in constraints):
        raise TypeError("project_constraints must be a list of objects")

    for row in gaps:
        if any(method_id not in method_ids for method_id in row.get("trigger_method_ids", [])):
            raise ValueError(f"platform gap {row['gap_id']} references a non-active method")
    for row in innovations:
        if any(method_id not in method_ids for method_id in row.get("parent_method_ids", [])):
            raise ValueError(f"innovation {row['innovation_id']} references a non-active method")
        if any(blocker not in innovation_ids for blocker in row.get("blocked_by_innovation_ids", [])):
            raise ValueError(f"innovation {row['innovation_id']} references an unknown innovation")
    for row in constraints:
        for forbidden in row.get("forbidden_method_features", []):
            if forbidden.get("method_id") not in method_ids:
                raise ValueError(f"project constraint {row.get('project_id')} references a non-active method")

    return {
        "schema": PROGRAM_SCHEMA,
        "authority": PROGRAM_AUTHORITY,
        "updated_at": control.get("updated_at"),
        "policy": control.get("policy"),
        "benchmarks": benchmark_rows,
        "methods": method_rows,
        "platform_gaps": gaps,
        "innovation_tracks": innovations,
        "project_constraints": constraints,
    }


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def sync(root: Path, *, check: bool) -> tuple[str, ...]:
    path = root / "research/catalog/research_program.json"
    expected = _render(project(root))
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    drift: list[str] = []
    if current != expected:
        if check:
            drift.append(str(path.relative_to(root)))
        else:
            path.write_text(expected, encoding="utf-8")
    print(json.dumps({
        "schema": PROGRAM_SCHEMA,
        "drift_count": len(drift),
        "drift": drift,
    }, ensure_ascii=False, sort_keys=True))
    return tuple(drift)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose the single-writer canonical research program projection.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    drift = sync(args.root.resolve(), check=args.check)
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
