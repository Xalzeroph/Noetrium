from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "research/catalog/publication_quality_policy.json"
REGISTRY_PATH = ROOT / "research/catalog/publication_registry.json"
REPRODUCTION_CATALOG_PATH = ROOT / "research/catalog/reproduction_catalog.json"
PRESSURE_SUITE_PATH = ROOT / "research/catalog/pressure_suite.json"
PRESSURE_STATUS_PATH = ROOT / "research/catalog/pressure_status.json"
OUTPUT_PATH = ROOT / "research/catalog/publication_priority_queue.json"

POLICY_SCHEMA = "noetrium.publication-quality-policy.v1"
REGISTRY_SCHEMA = "noetrium.publication-registry.v1"
OUTPUT_SCHEMA = "noetrium.publication-priority-queue.v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _priority_orders(policy: Mapping[str, Any]) -> dict[str, int]:
    raw = policy.get("priority_classes")
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("publication quality policy requires priority_classes")
    result: dict[str, int] = {}
    for name, row in raw.items():
        if not isinstance(name, str) or not isinstance(row, Mapping):
            raise TypeError("publication priority classes must be named objects")
        order = row.get("order")
        venues = row.get("venues")
        if type(order) is not int or order <= 0:
            raise ValueError(f"priority class {name} requires positive order")
        if not isinstance(venues, list) or not venues or any(
            not isinstance(item, str) or not item for item in venues
        ):
            raise ValueError(f"priority class {name} requires venues")
        result[name] = order
    return result


def _validate_registry(
    policy: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], tuple[str, ...]]:
    if policy.get("schema") != POLICY_SCHEMA:
        raise ValueError("publication quality policy schema mismatch")
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("publication registry schema mismatch")

    eligible_statuses = policy.get("eligible_publication_statuses")
    if not isinstance(eligible_statuses, list) or not eligible_statuses:
        raise ValueError("eligible_publication_statuses must be non-empty")
    eligible_status_set = set(eligible_statuses)

    priority_classes = policy.get("priority_classes")
    assert isinstance(priority_classes, Mapping)
    _priority_orders(policy)

    rows = registry.get("publications")
    if not isinstance(rows, list):
        raise TypeError("publication registry publications must be a list")

    by_id: dict[str, Mapping[str, Any]] = {}
    errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"publications[{index}] must be an object")
            continue
        publication_id = row.get("id")
        kind = row.get("kind")
        venue = row.get("venue")
        status = row.get("publication_status")
        priority_class = row.get("priority_class")
        if not isinstance(publication_id, str) or not publication_id:
            errors.append(f"publications[{index}] missing id")
            continue
        if publication_id in by_id:
            errors.append(f"duplicate publication id: {publication_id}")
            continue
        by_id[publication_id] = row
        if kind not in {"method", "benchmark"}:
            errors.append(f"{publication_id}: kind must be method or benchmark")
        if status not in eligible_status_set:
            errors.append(f"{publication_id}: publication status is not eligible")
        if not isinstance(priority_class, str) or priority_class not in priority_classes:
            errors.append(f"{publication_id}: unknown priority class")
            continue
        class_row = priority_classes[priority_class]
        assert isinstance(class_row, Mapping)
        venues = class_row.get("venues")
        if not isinstance(venues, list) or venue not in venues:
            errors.append(
                f"{publication_id}: venue {venue!r} is not admitted by {priority_class}"
            )
        year = row.get("year")
        if type(year) is not int or year < 2000:
            errors.append(f"{publication_id}: invalid publication year")
        evidence_url = row.get("evidence_url")
        if not isinstance(evidence_url, str) or not evidence_url.startswith("https://"):
            errors.append(f"{publication_id}: evidence_url must be HTTPS")
    return by_id, tuple(errors)


def _reproduction_index() -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    catalog = _load(REPRODUCTION_CATALOG_PATH)
    rows = catalog.get("methods")
    if not isinstance(rows, list):
        raise TypeError("reproduction catalog methods must be a list")
    by_method: dict[str, Mapping[str, Any]] = {}
    package_to_method: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("reproduction catalog method rows must be objects")
        method_id = row.get("method_id")
        if not isinstance(method_id, str) or not method_id:
            raise ValueError("reproduction catalog method requires method_id")
        by_method[method_id] = row
        packages = row.get("reproduction_packages", [])
        if not isinstance(packages, list):
            raise TypeError(f"{method_id}: reproduction_packages must be a list")
        for package in packages:
            if not isinstance(package, Mapping):
                raise TypeError(f"{method_id}: package row must be an object")
            package_name = package.get("package")
            if not isinstance(package_name, str) or not package_name:
                raise ValueError(f"{method_id}: package name missing")
            if package_name in package_to_method:
                raise ValueError(f"duplicate reproduction package: {package_name}")
            package_to_method[package_name] = method_id
    return by_method, package_to_method


def project() -> tuple[dict[str, Any], tuple[str, ...]]:
    policy = _load(POLICY_PATH)
    registry = _load(REGISTRY_PATH)
    by_publication, registry_errors = _validate_registry(policy, registry)
    priority_orders = _priority_orders(policy)
    reproductions, package_to_method = _reproduction_index()

    method_publications = {
        row.get("reproduction_method_id"): row
        for row in by_publication.values()
        if row.get("kind") == "method"
        and isinstance(row.get("reproduction_method_id"), str)
    }
    benchmark_publications = {
        row.get("benchmark_id"): row
        for row in by_publication.values()
        if row.get("kind") == "benchmark"
        and isinstance(row.get("benchmark_id"), str)
    }

    suite = _load(PRESSURE_SUITE_PATH)
    lanes = suite.get("lanes")
    if not isinstance(lanes, list):
        raise TypeError("pressure suite lanes must be a list")
    pressure_packages: set[str] = set()
    pressure_violations: list[str] = []
    for row in lanes:
        if not isinstance(row, Mapping):
            pressure_violations.append("pressure lane must be an object")
            continue
        package = row.get("package")
        if not isinstance(package, str) or not package:
            pressure_violations.append("pressure lane package missing")
            continue
        pressure_packages.add(package)
        method_id = package_to_method.get(package)
        if method_id is None:
            pressure_violations.append(f"{package}: no typed reproduction method")
            continue
        publication = method_publications.get(method_id)
        if publication is None:
            pressure_violations.append(
                f"{package}: method {method_id!r} has no eligible peer-reviewed publication"
            )

    pressure_ready: dict[str, bool] = {}
    if PRESSURE_STATUS_PATH.is_file():
        status = _load(PRESSURE_STATUS_PATH)
        status_rows = status.get("lanes", [])
        if isinstance(status_rows, list):
            for row in status_rows:
                if isinstance(row, Mapping):
                    package = row.get("package")
                    ready = row.get("ready")
                    if isinstance(package, str) and type(ready) is bool:
                        pressure_ready[package] = ready

    method_queue: list[dict[str, Any]] = []
    for publication in by_publication.values():
        if publication.get("kind") != "method":
            continue
        method_id = publication.get("reproduction_method_id")
        reproduction = (
            reproductions.get(method_id)
            if isinstance(method_id, str)
            else None
        )
        packages: list[str] = []
        lifecycles: list[str] = []
        if reproduction is not None:
            raw_packages = reproduction.get("reproduction_packages", [])
            if isinstance(raw_packages, list):
                for package in raw_packages:
                    if not isinstance(package, Mapping):
                        continue
                    name = package.get("package")
                    lifecycle = package.get("lifecycle")
                    if isinstance(name, str):
                        packages.append(name)
                    if isinstance(lifecycle, str):
                        lifecycles.append(lifecycle)
        active_packages = sorted(set(packages).intersection(pressure_packages))
        if not packages:
            implementation_state = "missing_reproduction"
        elif active_packages:
            implementation_state = (
                "pressure_ready"
                if any(pressure_ready.get(package, False) for package in active_packages)
                else "active_pressure_gap"
            )
        else:
            implementation_state = "reproduction_exists_not_active_pressure"

        method_queue.append(
            {
                "publication_id": publication["id"],
                "title": publication["title"],
                "year": publication["year"],
                "venue": publication["venue"],
                "priority_class": publication["priority_class"],
                "priority_order": priority_orders[str(publication["priority_class"])],
                "method_id": method_id,
                "packages": sorted(packages),
                "lifecycles": sorted(set(lifecycles)),
                "pressure_packages": active_packages,
                "implementation_state": implementation_state,
            }
        )
    method_queue.sort(
        key=lambda row: (
            row["priority_order"],
            0 if row["implementation_state"] == "active_pressure_gap" else
            1 if row["implementation_state"] == "missing_reproduction" else
            2 if row["implementation_state"] == "reproduction_exists_not_active_pressure" else 3,
            -int(row["year"]),
            str(row["publication_id"]),
        )
    )

    benchmark_catalog = _load(ROOT / "research/catalog/benchmark_catalog.json")
    benchmark_rows = benchmark_catalog.get("benchmarks")
    if not isinstance(benchmark_rows, list):
        raise TypeError("benchmark catalog benchmarks must be a list")
    existing_benchmarks = {
        row.get("benchmark_id")
        for row in benchmark_rows
        if isinstance(row, Mapping) and isinstance(row.get("benchmark_id"), str)
    }
    benchmark_queue = [
        {
            "publication_id": publication["id"],
            "title": publication["title"],
            "year": publication["year"],
            "venue": publication["venue"],
            "priority_class": publication["priority_class"],
            "priority_order": priority_orders[str(publication["priority_class"])],
            "benchmark_id": benchmark_id,
            "adapter_state": (
                "manifest_present"
                if benchmark_id in existing_benchmarks
                else "missing_adapter"
            ),
        }
        for benchmark_id, publication in benchmark_publications.items()
    ]
    benchmark_queue.sort(
        key=lambda row: (
            row["priority_order"],
            0 if row["adapter_state"] == "missing_adapter" else 1,
            -int(row["year"]),
            str(row["publication_id"]),
        )
    )

    ineligible = registry.get("explicitly_ineligible_current_items", [])
    if not isinstance(ineligible, list):
        raise TypeError("explicitly_ineligible_current_items must be a list")
    ineligible_method_ids = {
        row.get("method_id")
        for row in ineligible
        if isinstance(row, Mapping) and isinstance(row.get("method_id"), str)
    }
    leaked_ineligible = sorted(
        {
            package_to_method[package]
            for package in pressure_packages
            if package in package_to_method
            and package_to_method[package] in ineligible_method_ids
        }
    )
    for method_id in leaked_ineligible:
        pressure_violations.append(
            f"ineligible preprint/non-qualifying method leaked into pressure suite: {method_id}"
        )

    errors = tuple(sorted(set((*registry_errors, *pressure_violations))))
    return (
        {
            "schema": OUTPUT_SCHEMA,
            "authority": "generated_from_publication_policy_registry_reproduction_and_pressure_projections",
            "updated_at": registry.get("updated_at"),
            "method_count": len(method_queue),
            "benchmark_count": len(benchmark_queue),
            "formal_pressure_violation_count": len(pressure_violations),
            "method_queue": method_queue,
            "benchmark_queue": benchmark_queue,
            "explicitly_ineligible_current_items": ineligible,
        },
        errors,
    )


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project and enforce peer-reviewed publication priority."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)

    projection, errors = project()
    expected = _render(projection)
    current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.is_file() else ""
    drift = current != expected
    if not args.check and drift:
        OUTPUT_PATH.write_text(expected, encoding="utf-8")
        drift = False

    print(
        json.dumps(
            {
                "schema": OUTPUT_SCHEMA,
                "method_count": projection["method_count"],
                "benchmark_count": projection["benchmark_count"],
                "projection_drift": drift,
                "error_count": len(errors),
                "errors": errors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if errors:
        return 1
    if args.check and drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
