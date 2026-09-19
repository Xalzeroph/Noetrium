from __future__ import annotations

import argparse
import ast
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.kernel.kernel import canonical_digest, thaw_json
from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceRegistry,
    PublicationSourceLane,
    SourceLane,
)
from noetrium_platform.research.reproduction import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetRef,
    ReproductionDefinition,
    ReproductionDelta,
)

PROJECTION_SCHEMA = "noetrium.reproduction.projection.v5"
REPRODUCTION_CATALOG_SCHEMA = "noetrium.reproduction-catalog.projection.v1"
REPRODUCTION_CATALOG_AUTHORITY = "generated_from_typed_reproduction_definitions"
_ALLOWED_DEFINITION_IMPORTS = {"__future__", "noetrium_platform.research.reproduction"}
_ALLOWED_SOURCE_IMPORTS = {
    "__future__",
    "noetrium_platform.research.provenance",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _restricted_imports(path: Path, allowed: set[str]) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {row.name for row in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError(f"{path} may not use relative imports")
            names = {node.module or ""}
        else:
            continue
        unknown = sorted(name for name in names if name not in allowed)
        if unknown:
            raise ValueError(f"{path} imports non-authority modules: {unknown}")


def _load_module(path: Path, *, suffix: str) -> ModuleType:
    name = f"_noetrium_reproduction_{path.parent.name}_{suffix}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _definition(package_dir: Path) -> ReproductionDefinition:
    path = package_dir / "definition.py"
    if not path.is_file():
        raise FileNotFoundError(f"missing typed reproduction authority: {path}")
    _restricted_imports(path, _ALLOWED_DEFINITION_IMPORTS)
    value = getattr(_load_module(path, suffix="definition"), "REPRODUCTION", None)
    if type(value) is not ReproductionDefinition:
        raise TypeError(f"{path}: REPRODUCTION must be ReproductionDefinition")
    if value.package != package_dir.name:
        raise ValueError(f"{path}: package identity mismatch")
    return value


def _sources(package_dir: Path) -> MethodSourceRegistry:
    path = package_dir / "source.py"
    if not path.is_file():
        raise FileNotFoundError(f"missing typed reproduction source authority: {path}")
    _restricted_imports(path, _ALLOWED_SOURCE_IMPORTS)
    value = getattr(_load_module(path, suffix="source"), "SOURCES", None)
    if type(value) is not MethodSourceRegistry:
        raise TypeError(f"{path}: SOURCES must be MethodSourceRegistry")
    return value


def _lane(row: SourceLane) -> dict[str, Any]:
    if type(row) is MethodSourceLane:
        return {
            "lane_id": row.lane_id,
            "kind": row.kind.value,
            "repository": row.repository,
            "commit": row.commit,
            "artifacts": list(row.artifacts),
            "lane_digest": row.lane_digest,
        }
    if type(row) is PublicationSourceLane:
        return {
            "lane_id": row.lane_id,
            "kind": row.kind.value,
            "venue": row.venue,
            "year": row.year,
            "publication_id": row.publication_id,
            "publication_uri": row.publication_uri,
            "revision": row.revision,
            "content_sha256": row.content_sha256,
            "lane_digest": row.lane_digest,
        }
    raise TypeError("unsupported reproduction source lane")


def _file_sha256(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _asset(row: ReproductionAssetRef) -> dict[str, Any]:
    return {
        "kind": row.kind.value,
        "path": row.path,
        "declaration_digest": row.declaration_digest,
        "content_sha256": _file_sha256(row.path),
    }


def _scientific_test(path: str) -> dict[str, Any]:
    return {"path": path, "content_sha256": _file_sha256(path)}


def _claim(row: ReportedResult) -> dict[str, Any]:
    return {
        "claim_id": row.claim_id,
        "metric_id": row.metric_id,
        "value": row.value,
        "qualifiers": thaw_json(row.qualifiers),
        "claim_digest": row.claim_digest,
    }


def _baseline(row: ReferenceBaseline) -> dict[str, Any]:
    return {
        "baseline_id": row.baseline_id,
        "description": row.description,
        "qualifiers": thaw_json(row.qualifiers),
        "baseline_digest": row.baseline_digest,
    }


def _delta(row: ReproductionDelta) -> dict[str, Any]:
    return {
        "kind": row.kind.value,
        "description": row.description,
        "delta_digest": row.delta_digest,
    }


def _projection(
    definition: ReproductionDefinition,
    sources: MethodSourceRegistry,
) -> dict[str, Any]:
    assets = [_asset(row) for row in definition.assets]
    scientific_tests = [_scientific_test(path) for path in definition.scientific_tests]
    package_digest = canonical_digest(
        {
            "definition_digest": definition.definition_digest,
            "source_registry_digest": sources.registry_digest,
            "assets": assets,
            "scientific_tests": scientific_tests,
        }
    )
    return {
        "schema": PROJECTION_SCHEMA,
        "authority": "generated_from_typed_definition_and_source",
        "package": definition.package,
        "package_digest": package_digest,
        "definition_digest": definition.definition_digest,
        "source_registry_digest": sources.registry_digest,
        "lifecycle": definition.lifecycle.value,
        "identity": {
            "method_id": definition.identity.method_id,
            "title": definition.identity.title,
            "paper_uri": definition.identity.paper_uri,
            "year": definition.identity.year,
            "paper_revision": definition.identity.paper_revision,
            "identity_digest": definition.identity.identity_digest,
        },
        "catalog": {
            "domains": list(definition.catalog.domains),
            "families": list(definition.catalog.families),
            "priority": definition.catalog.priority,
            "benchmark_ids": list(definition.catalog.benchmark_ids),
            "platform_pressure": list(definition.catalog.platform_pressure),
            "method_owned": list(definition.catalog.method_owned),
            "platform_owned": list(definition.catalog.platform_owned),
            "reference_repositories": list(sources.repositories),
            "reference_publications": list(sources.publication_uris),
            "catalog_digest": definition.catalog.catalog_digest,
        },
        "source_lanes": [_lane(row) for row in sources.lanes],
        "assets": assets,
        "primary_executable": definition.primary_executable,
        "reported_results": [_claim(row) for row in definition.reported_results],
        "reference_baselines": [_baseline(row) for row in definition.reference_baselines],
        "deltas": [_delta(row) for row in definition.deltas],
        "blockers": list(definition.blockers),
        "evidence_refs": list(definition.evidence_refs),
        "scientific_tests": scientific_tests,
    }


def _validate_paths(
    package_dir: Path,
    definition: ReproductionDefinition,
) -> None:
    package_prefix = package_dir.relative_to(ROOT).as_posix() + "/"
    for asset in definition.assets:
        if not asset.path.startswith(package_prefix):
            raise ValueError(
                f"{package_dir}: scientific asset must remain inside its reproduction package: {asset.path}"
            )
        if not (ROOT / asset.path).is_file():
            raise FileNotFoundError(f"missing reproduction asset: {asset.path}")
    for test in definition.scientific_tests:
        if not test.startswith("tests/test_scientific_") or not test.endswith(".py"):
            raise ValueError(f"scientific test path is not canonical: {test}")
        if not (ROOT / test).is_file():
            raise FileNotFoundError(f"missing scientific test: {test}")


def _merge_method_rows(
    rows: list[tuple[ReproductionDefinition, MethodSourceRegistry]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[tuple[ReproductionDefinition, MethodSourceRegistry]]] = {}
    for definition, sources in rows:
        grouped.setdefault(definition.identity.method_id, []).append((definition, sources))

    result: list[dict[str, Any]] = []
    for method_id, group in sorted(grouped.items()):
        identities = {
            (
                row.identity.title,
                row.identity.paper_uri,
                row.identity.year,
            )
            for row, _ in group
        }
        if len(identities) != 1:
            raise ValueError(f"reproduction method identity drift across packages: {method_id}")
        title, paper_uri, year = next(iter(identities))
        reproduction_packages = [
            {"package": row.package, "lifecycle": row.lifecycle.value}
            for row, _ in sorted(group, key=lambda item: item[0].package)
        ]
        if len({row["package"] for row in reproduction_packages}) != len(reproduction_packages):
            raise ValueError(f"duplicate reproduction package for method: {method_id}")
        result.append(
            {
                "method_id": method_id,
                "title": title,
                "paper_uri": paper_uri,
                "year": year,
                "families": sorted({value for row, _ in group for value in row.catalog.families}),
                "reference_repositories": sorted(
                    {value for _, sources in group for value in sources.repositories}
                ),
                "reproduction_packages": reproduction_packages,
                "priority": min(row.catalog.priority for row, _ in group),
                "benchmark_ids": sorted(
                    {value for row, _ in group for value in row.catalog.benchmark_ids}
                ),
                "platform_pressure": sorted(
                    {value for row, _ in group for value in row.catalog.platform_pressure}
                ),
                "method_owned": sorted(
                    {value for row, _ in group for value in row.catalog.method_owned}
                ),
                "platform_owned": sorted(
                    {value for row, _ in group for value in row.catalog.platform_owned}
                ),
                "evidence_refs": sorted(
                    {value for row, _ in group for value in row.evidence_refs}
                ),
            }
        )
    return result


def _render_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False, indent=2) + "\n"


def sync(*, check: bool) -> int:
    root = ROOT / "research/reproductions"
    package_dirs = tuple(
        sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and not path.name.startswith("__")
        )
    )
    rows: list[tuple[ReproductionDefinition, MethodSourceRegistry]] = []
    drift: list[str] = []

    for package_dir in package_dirs:
        definition = _definition(package_dir)
        sources = _sources(package_dir)
        _validate_paths(package_dir, definition)
        rows.append((definition, sources))
        projection_path = package_dir / "reproduction.json"
        expected = _render_json(_projection(definition, sources))
        current = projection_path.read_text(encoding="utf-8") if projection_path.is_file() else ""
        if current != expected:
            if check:
                drift.append(projection_path.relative_to(ROOT).as_posix())
            else:
                projection_path.write_text(expected, encoding="utf-8")

    reproduction_catalog_path = ROOT / "research/catalog/reproduction_catalog.json"
    reproduction_catalog = {
        "schema": REPRODUCTION_CATALOG_SCHEMA,
        "authority": REPRODUCTION_CATALOG_AUTHORITY,
        "methods": _merge_method_rows(rows),
    }
    expected_catalog = _render_json(reproduction_catalog)
    current_catalog = (
        reproduction_catalog_path.read_text(encoding="utf-8")
        if reproduction_catalog_path.is_file()
        else ""
    )
    if current_catalog != expected_catalog:
        if check:
            drift.append(reproduction_catalog_path.relative_to(ROOT).as_posix())
        else:
            reproduction_catalog_path.write_text(expected_catalog, encoding="utf-8")

    scope_path = ROOT / "research/catalog/agent_reproduction_scope.json"
    scope = _load_json(scope_path)
    seed_rows = scope.get("seed_lineages")
    if not isinstance(seed_rows, list):
        raise TypeError("agent_reproduction_scope.seed_lineages must be a list")
    seeds = {
        row.get("id"): row
        for row in seed_rows
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    publication_path = ROOT / "research/catalog/publication_registry.json"
    publication_registry = _load_json(publication_path)
    publication_rows = publication_registry.get("publications")
    if not isinstance(publication_rows, list):
        raise TypeError("publication_registry.publications must be a list")
    formal_publications = {
        row.get("reproduction_method_id"): row
        for row in publication_rows
        if isinstance(row, Mapping)
        and row.get("kind") == "method"
        and isinstance(row.get("reproduction_method_id"), str)
    }

    for definition, _ in rows:
        method_id = definition.identity.method_id
        seed = seeds.get(method_id)
        formal = formal_publications.get(method_id)

        # A peer-reviewed publication is the strongest discovery authority.
        # Seed lineages remain a fallback for work that has not yet acquired a
        # formal publication record. Requiring both would create two manual
        # sources of truth for every new reproduction.
        if formal is not None:
            # Publication evidence proves peer-reviewed status; it is not
            # necessarily the same artifact URI used by a paper-era
            # reproduction (for example, an arXiv paper cut can later acquire
            # an IEEE/ACM/OpenReview proceedings record). The explicit
            # reproduction_method_id binding is authoritative for method
            # identity, while title and publication year guard against an
            # accidental registry cross-link.
            formal_matches = (
                formal.get("title") == definition.identity.title
                and formal.get("year") == definition.identity.year
            )
            if not formal_matches:
                raise ValueError(
                    "typed reproduction identity conflicts with formal "
                    f"publication authority: {method_id}"
                )
            continue

        if seed is None:
            raise ValueError(
                f"typed reproduction is outside discovery authority: {method_id}"
            )

        discovery_matches = (
            seed.get("source") == definition.identity.paper_uri
            and seed.get("year") == definition.identity.year
        )
        if not discovery_matches:
            raise ValueError(
                "typed reproduction identity conflicts with discovery "
                f"authority: {method_id}"
            )

    report = {
        "schema": PROJECTION_SCHEMA,
        "package_count": len(rows),
        "drift_count": len(drift),
        "drift": sorted(drift),
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if drift else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project typed reproduction definitions into generated JSON and catalogs."
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    return sync(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
