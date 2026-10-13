from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from noetrium_platform.capabilities.environment.category.api import EnvironmentCategoryId

MANIFEST_SCHEMA = "noetrium.benchmark-manifest.v2"
CATALOG_SCHEMA = "noetrium.benchmark-catalog.projection.v2"
CATALOG_AUTHORITY = "generated_from_benchmark_manifests"
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_ALLOWED_ENVIRONMENT_KINDS = frozenset(
    item.value for item in EnvironmentCategoryId
)
_CORE_MODALITIES = frozenset(
    {"text", "image", "video", "audio", "code", "structured", "tensor"}
)


@dataclass(frozen=True, slots=True)
class BenchmarkManifestFinding:
    code: str
    path: str
    detail: str


def _load_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _text(value: object, path: str, findings: list[BenchmarkManifestFinding]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        findings.append(BenchmarkManifestFinding("INVALID_TEXT", path, "expected canonical non-empty text"))
        return ""
    return value


def _token(value: object, path: str, findings: list[BenchmarkManifestFinding]) -> str:
    text = _text(value, path, findings)
    if text and not _TOKEN.fullmatch(text):
        findings.append(BenchmarkManifestFinding("INVALID_TOKEN", path, text))
    return text


def _string_list(value: object, path: str, findings: list[BenchmarkManifestFinding]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        findings.append(BenchmarkManifestFinding("INVALID_STRING_LIST", path, "expected canonical string list"))
        return ()
    rows = tuple(value)
    if len(rows) != len(set(rows)):
        findings.append(BenchmarkManifestFinding("DUPLICATE_LIST_VALUE", path, "values must be unique"))
    return rows


def project(root: Path) -> tuple[Mapping[str, Any], tuple[BenchmarkManifestFinding, ...]]:
    findings: list[BenchmarkManifestFinding] = []
    benchmarks_root = root / "research/benchmarks"
    packages = tuple(
        sorted(path.name for path in benchmarks_root.iterdir() if path.is_dir() and not path.name.startswith("__"))
    )
    desired: dict[str, Mapping[str, Any]] = {}
    for package in packages:
        manifest_path = benchmarks_root / package / "manifest.json"
        relative = str(manifest_path.relative_to(root))
        if not manifest_path.is_file():
            findings.append(BenchmarkManifestFinding(
                "MISSING_BENCHMARK_MANIFEST",
                relative,
                "every benchmark package must own exactly one manifest",
            ))
            continue
        manifest = _load_object(manifest_path)
        if set(manifest) != {"schema", "package", "benchmark"}:
            findings.append(BenchmarkManifestFinding("MANIFEST_SHAPE_MISMATCH", relative, "expected schema/package/benchmark"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            findings.append(BenchmarkManifestFinding("MANIFEST_SCHEMA_MISMATCH", f"{relative}.schema", MANIFEST_SCHEMA))
        if manifest.get("package") != package:
            findings.append(BenchmarkManifestFinding("PACKAGE_IDENTITY_MISMATCH", f"{relative}.package", package))
        row = manifest.get("benchmark")
        if not isinstance(row, Mapping):
            findings.append(BenchmarkManifestFinding("INVALID_BENCHMARK", f"{relative}.benchmark", "expected object"))
            continue
        expected = {
            "benchmark_id",
            "title",
            "source_uri",
            "environment_kinds",
            "modalities",
        }
        if set(row) != expected:
            findings.append(BenchmarkManifestFinding("BENCHMARK_SHAPE_MISMATCH", f"{relative}.benchmark", f"expected keys {sorted(expected)}"))
        benchmark_id = _token(row.get("benchmark_id"), f"{relative}.benchmark.benchmark_id", findings)
        _text(row.get("title"), f"{relative}.benchmark.title", findings)
        source_uri = _text(row.get("source_uri"), f"{relative}.benchmark.source_uri", findings)
        if source_uri and not source_uri.startswith("https://"):
            findings.append(BenchmarkManifestFinding("NON_HTTPS_SOURCE", f"{relative}.benchmark.source_uri", source_uri))
        environment_kinds = _string_list(
            row.get("environment_kinds"),
            f"{relative}.benchmark.environment_kinds",
            findings,
        )
        unknown = sorted(
            set(environment_kinds) - _ALLOWED_ENVIRONMENT_KINDS
        )
        if unknown:
            findings.append(
                BenchmarkManifestFinding(
                    "UNKNOWN_ENVIRONMENT_KIND",
                    f"{relative}.benchmark.environment_kinds",
                    ", ".join(unknown),
                )
            )

        modalities = _string_list(
            row.get("modalities"),
            f"{relative}.benchmark.modalities",
            findings,
        )
        if not modalities:
            findings.append(
                BenchmarkManifestFinding(
                    "MISSING_MODALITY",
                    f"{relative}.benchmark.modalities",
                    "every benchmark must declare at least one content modality",
                )
            )
        invalid_modalities = tuple(
            modality
            for modality in modalities
            if not _TOKEN.fullmatch(modality)
        )
        if invalid_modalities:
            findings.append(
                BenchmarkManifestFinding(
                    "INVALID_MODALITY_TOKEN",
                    f"{relative}.benchmark.modalities",
                    ", ".join(invalid_modalities),
                )
            )
        if benchmark_id:
            if benchmark_id in desired:
                findings.append(BenchmarkManifestFinding("DUPLICATE_BENCHMARK_ID", relative, benchmark_id))
            desired[benchmark_id] = dict(row)

    return {
        "schema": CATALOG_SCHEMA,
        "authority": CATALOG_AUTHORITY,
        "benchmarks": [desired[key] for key in sorted(desired)],
    }, tuple(findings)


def _render(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def sync_benchmark_manifests(root: Path, *, check: bool) -> tuple[BenchmarkManifestFinding, ...]:
    projected, findings = project(root)
    if findings:
        print(json.dumps({
            "schema": CATALOG_SCHEMA,
            "finding_count": len(findings),
            "findings": [asdict(row) for row in findings],
        }, ensure_ascii=False, sort_keys=True))
        return findings

    path = root / "research/catalog/benchmark_catalog.json"
    expected = _render(projected)
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    drift: list[BenchmarkManifestFinding] = []
    if current != expected:
        if check:
            drift.append(BenchmarkManifestFinding(
                "BENCHMARK_CATALOG_DRIFT",
                str(path.relative_to(root)),
                "run scripts/sync_benchmark_manifests.py",
            ))
        else:
            path.write_text(expected, encoding="utf-8")

    print(json.dumps({
        "schema": CATALOG_SCHEMA,
        "benchmark_count": len(projected["benchmarks"]),
        "drift_count": len(drift),
        "drift": [asdict(row) for row in drift],
    }, ensure_ascii=False, sort_keys=True))
    return tuple(drift)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project benchmark manifests into the benchmark catalog.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings = sync_benchmark_manifests(args.root.resolve(), check=args.check)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
