from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "research/catalog/pressure_suite.json"
STATUS_PATH = ROOT / "research/catalog/pressure_status.json"

SUITE_SCHEMA = "noetrium.research-pressure-suite.v2"
STATUS_SCHEMA = "noetrium.research-pressure-status.v1"

_LIFECYCLE_RANK = {
    "catalogued": 0,
    "paper_only": 0,
    "artifact_only": 0,
    "protocol_bound": 1,
    "runnable": 2,
    "pilot": 3,
    "matched_reproduction": 4,
    "blocked": -1,
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _asset_map(projection: Mapping[str, Any]) -> dict[str, list[str]]:
    rows = projection.get("assets")
    if not isinstance(rows, list):
        raise TypeError("reproduction projection assets must be a list")
    result: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("reproduction asset row must be an object")
        kind = row.get("kind")
        path = row.get("path")
        if not isinstance(kind, str) or not isinstance(path, str):
            raise TypeError("reproduction asset row kind/path must be text")
        result.setdefault(kind, []).append(path)
    return result


def _ast_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _benchmark_index() -> dict[str, tuple[str, Path]]:
    catalog = _load(ROOT / "research/catalog/benchmark_catalog.json")
    rows = catalog.get("benchmarks")
    if not isinstance(rows, list):
        raise TypeError("benchmark catalog benchmarks must be a list")

    manifests: dict[str, tuple[str, Path]] = {}
    for manifest_path in sorted((ROOT / "research/benchmarks").glob("*/manifest.json")):
        manifest = _load(manifest_path)
        benchmark = manifest.get("benchmark")
        if not isinstance(benchmark, Mapping):
            continue
        benchmark_id = benchmark.get("benchmark_id")
        package = manifest.get("package")
        if isinstance(benchmark_id, str) and isinstance(package, str):
            manifests[benchmark_id] = (package, manifest_path.parent)

    catalog_ids = {
        row.get("benchmark_id")
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("benchmark_id"), str)
    }
    if catalog_ids != set(manifests):
        raise ValueError("benchmark manifest/catalog identity drift")
    return manifests


def _lane_status(
    row: Mapping[str, Any],
    *,
    required_asset_kinds: tuple[str, ...],
    executable_asset_kinds: tuple[str, ...],
    minimum_lifecycle: str,
    benchmark_index: Mapping[str, tuple[str, Path]],
) -> dict[str, Any]:
    package = row.get("package")
    lineage = row.get("lineage")
    enforced = row.get("enforced")
    if not isinstance(package, str) or not package:
        raise ValueError("pressure lane package must be non-empty")
    if not isinstance(lineage, str) or not lineage:
        raise ValueError(f"{package}: lineage must be non-empty")
    if type(enforced) is not bool:
        raise TypeError(f"{package}: enforced must be bool")

    projection_path = ROOT / "research/reproductions" / package / "reproduction.json"
    gaps: list[str] = []
    detail: dict[str, Any] = {
        "package": package,
        "lineage": lineage,
        "enforced": enforced,
    }
    if not projection_path.is_file():
        gaps.append("missing_reproduction_projection")
        detail.update({"ready": False, "gaps": gaps})
        return detail

    projection = _load(projection_path)
    lifecycle = projection.get("lifecycle")
    detail["lifecycle"] = lifecycle
    if not isinstance(lifecycle, str) or lifecycle not in _LIFECYCLE_RANK:
        gaps.append("invalid_lifecycle")
    elif _LIFECYCLE_RANK[lifecycle] < _LIFECYCLE_RANK[minimum_lifecycle]:
        gaps.append("lifecycle_below_protocol_bound")

    assets = _asset_map(projection)
    detail["asset_kinds"] = sorted(assets)
    for kind in required_asset_kinds:
        if not assets.get(kind):
            gaps.append(f"missing_asset:{kind}")

    fidelity_paths = assets.get("fidelity", [])
    for relative in fidelity_paths:
        if not (ROOT / relative).is_file():
            gaps.append("missing_fidelity_file")

    executable_assets = tuple(
        (kind, path)
        for kind in executable_asset_kinds
        for path in assets.get(kind, [])
    )
    executable_kinds = tuple(sorted({kind for kind, _ in executable_assets}))
    detail["executable_asset_kinds"] = list(executable_kinds)

    declared_primary = projection.get("primary_executable")
    primary: tuple[str, str] | None = None
    if not executable_assets:
        gaps.append("missing_executable_program")
    elif declared_primary is None:
        if len(executable_assets) == 1:
            primary = executable_assets[0]
        else:
            gaps.append("ambiguous_executable_program")
    elif not isinstance(declared_primary, str) or not declared_primary:
        gaps.append("invalid_primary_executable")
    else:
        matches = tuple(
            row for row in executable_assets if row[1] == declared_primary
        )
        if len(matches) != 1:
            gaps.append("invalid_primary_executable")
        else:
            primary = matches[0]

    if primary is not None:
        primary_kind, primary_path = primary
        detail["primary_executable"] = {
            "kind": primary_kind,
            "path": primary_path,
        }
        program_file = ROOT / primary_path
        if primary_kind == "method_program":
            if not program_file.is_file():
                gaps.append("missing_method_program_file")
            else:
                names = _ast_names(program_file)
                if (
                    "MethodProgram" not in names
                    and "MethodProgramBuilder" not in names
                ):
                    gaps.append("method_program_not_bound_to_umm")
        elif primary_kind == "research_program":
            if not program_file.is_file():
                gaps.append("missing_research_program_file")
            else:
                names = _ast_names(program_file)
                research_program_symbols = {
                    "ResearchProgram",
                    "ResearchProgramBuilder",
                    "RuntimeProgramBuilder",
                    "ParticipantProgramBuilder",
                    "EnvironmentProgramBuilder",
                    "MemoryProgramBuilder",
                    "EvaluationProgramBuilder",
                    "OptimizationProgramBuilder",
                    "ExperimentProgramBuilder",
                    "ResearchRunProgramBuilder",
                }
                if not names.intersection(research_program_symbols):
                    gaps.append(
                        "research_program_not_bound_to_universal_machine"
                    )
        else:
            gaps.append(
                f"unsupported_executable_program_kind:{primary_kind}"
            )

    study_paths = assets.get("study", [])
    if study_paths:
        study_file = ROOT / study_paths[0]
        if not study_file.is_file():
            gaps.append("missing_study_file")
        else:
            names = _ast_names(study_file)
            if "Study" not in names and "ResearchStudyDefinition" not in names:
                gaps.append("study_contract_missing")
            if "MeasurementDefinition" not in names:
                gaps.append("measurement_contract_missing")

    catalog = projection.get("catalog")
    benchmark_ids = (
        catalog.get("benchmark_ids")
        if isinstance(catalog, Mapping)
        else None
    )
    if not isinstance(benchmark_ids, list) or not benchmark_ids:
        gaps.append("benchmark_binding_missing")
        benchmark_ids = []
    detail["benchmark_ids"] = benchmark_ids
    benchmark_packages: list[str] = []
    for benchmark_id in benchmark_ids:
        if not isinstance(benchmark_id, str):
            gaps.append("invalid_benchmark_id")
            continue
        indexed = benchmark_index.get(benchmark_id)
        if indexed is None:
            gaps.append(f"benchmark_manifest_missing:{benchmark_id}")
            continue
        benchmark_package, benchmark_root = indexed
        benchmark_packages.append(benchmark_package)
        if not (benchmark_root / "cut.py").is_file():
            gaps.append(f"benchmark_cut_missing:{benchmark_id}")
    detail["benchmark_packages"] = sorted(benchmark_packages)

    tests = projection.get("scientific_tests")
    if not isinstance(tests, list) or not tests:
        gaps.append("scientific_tests_missing")
        tests = []
    detail["scientific_test_count"] = len(tests)

    detail["reported_result_count"] = len(projection.get("reported_results", []))
    detail["blocker_count"] = len(projection.get("blockers", []))
    detail["ready"] = not gaps
    detail["gaps"] = sorted(set(gaps))
    return detail


def project() -> dict[str, Any]:
    suite = _load(SUITE_PATH)
    if suite.get("schema") != SUITE_SCHEMA:
        raise ValueError("research pressure suite schema mismatch")
    closure = suite.get("closure_contract")
    if not isinstance(closure, Mapping):
        raise TypeError("pressure suite closure_contract must be an object")
    kinds = closure.get("required_asset_kinds")
    if (
        not isinstance(kinds, list)
        or not kinds
        or any(not isinstance(x, str) or not x for x in kinds)
        or len(kinds) != len(set(kinds))
    ):
        raise TypeError(
            "required_asset_kinds must be a unique non-empty string list"
        )
    executable_kinds = closure.get("executable_asset_kinds")
    if (
        not isinstance(executable_kinds, list)
        or not executable_kinds
        or any(
            not isinstance(x, str) or not x
            for x in executable_kinds
        )
        or len(executable_kinds) != len(set(executable_kinds))
    ):
        raise TypeError(
            "executable_asset_kinds must be a unique non-empty string list"
        )
    if set(kinds).intersection(executable_kinds):
        raise ValueError(
            "required and alternative executable asset kinds must be disjoint"
        )
    minimum_lifecycle = closure.get("minimum_lifecycle")
    if not isinstance(minimum_lifecycle, str) or minimum_lifecycle not in _LIFECYCLE_RANK:
        raise ValueError("invalid minimum_lifecycle")
    lanes = suite.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise TypeError("pressure suite lanes must be a non-empty list")

    benchmark_index = _benchmark_index()
    statuses = [
        _lane_status(
            row,
            required_asset_kinds=tuple(kinds),
            executable_asset_kinds=tuple(executable_kinds),
            minimum_lifecycle=minimum_lifecycle,
            benchmark_index=benchmark_index,
        )
        for row in lanes
        if isinstance(row, Mapping)
    ]
    if len(statuses) != len(lanes):
        raise TypeError("all pressure suite lanes must be objects")
    packages = [row["package"] for row in statuses]
    if len(packages) != len(set(packages)):
        raise ValueError("pressure suite package identities must be unique")

    enforced = [row for row in statuses if row["enforced"]]
    return {
        "schema": STATUS_SCHEMA,
        "authority": "generated_from_pressure_suite_reproduction_and_benchmark_projections",
        "suite_updated_at": suite.get("updated_at"),
        "lane_count": len(statuses),
        "ready_count": sum(bool(row["ready"]) for row in statuses),
        "enforced_count": len(enforced),
        "enforced_ready_count": sum(bool(row["ready"]) for row in enforced),
        "lanes": statuses,
    }


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project and enforce cross-lineage reproduction closure."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)

    status = project()
    expected = _render(status)
    current = STATUS_PATH.read_text(encoding="utf-8") if STATUS_PATH.is_file() else ""
    drift = current != expected
    if not args.check and drift:
        STATUS_PATH.write_text(expected, encoding="utf-8")
        drift = False

    enforced_failures = [
        row for row in status["lanes"]
        if row["enforced"] and not row["ready"]
    ]
    print(
        json.dumps(
            {
                "schema": STATUS_SCHEMA,
                "lane_count": status["lane_count"],
                "ready_count": status["ready_count"],
                "enforced_count": status["enforced_count"],
                "enforced_ready_count": status["enforced_ready_count"],
                "projection_drift": drift,
                "enforced_failures": [
                    {"package": row["package"], "gaps": row["gaps"]}
                    for row in enforced_failures
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.check and drift:
        return 1
    if args.enforce and enforced_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
