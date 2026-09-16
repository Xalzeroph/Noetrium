from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


MANIFEST_SCHEMA = "noetrium.reproduction-manifest.v1"
POLICY_SCHEMA = "noetrium.reproduction-manifest-policy.v1"
SCOPE_SCHEMA = "noetrium.agent-reproduction-scope.v1"
PROGRAM_SCHEMA = "noetrium.research-program.v1"
_SHA40 = re.compile(r"[0-9a-f]{40}")
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_ALLOWED_REPRODUCTION_STATUS = {
    "queued",
    "audited",
    "scaffolded",
    "pilot",
    "matched_reproduction",
}
_INITIAL_LEGACY_PACKAGES = frozenset(
    {
        "adas_meta_agent_search",
        "autogen_agentchat",
        "camel_role_playing",
        "generative_agents_memory",
        "lats_webshop",
        "live_swe_agent",
        "memevolve",
        "memgpt_classic",
        "metagpt_software_company",
        "multiagent_debate",
        "rap_reasoning",
        "react_alfworld",
        "reflexion_alfworld",
        "self_refine",
        "swe_agent_swebench",
        "toolllm_toolbench",
        "tree_of_thoughts",
        "voyager_minecraft",
        "webvoyager",
    }
)


@dataclass(frozen=True, slots=True)
class ManifestFinding:
    code: str
    path: str
    detail: str


def _load_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _text(value: object, path: str, findings: list[ManifestFinding]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        findings.append(ManifestFinding("INVALID_TEXT", path, "expected canonical non-empty text"))
        return ""
    return value


def _token(value: object, path: str, findings: list[ManifestFinding]) -> str:
    text = _text(value, path, findings)
    if text and not _TOKEN.fullmatch(text):
        findings.append(ManifestFinding("INVALID_TOKEN", path, text))
    return text


def _string_list(value: object, path: str, findings: list[ManifestFinding], *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        findings.append(ManifestFinding("INVALID_STRING_LIST", path, "expected canonical string list"))
        return ()
    rows = tuple(value)
    if non_empty and not rows:
        findings.append(ManifestFinding("EMPTY_STRING_LIST", path, "list must not be empty"))
    if len(rows) != len(set(rows)):
        findings.append(ManifestFinding("DUPLICATE_LIST_VALUE", path, "values must be unique"))
    return rows


def _https(value: object, path: str, findings: list[ManifestFinding]) -> str:
    text = _text(value, path, findings)
    if text and not text.startswith("https://"):
        findings.append(ManifestFinding("NON_HTTPS_URI", path, text))
    return text


def _object(value: object, path: str, findings: list[ManifestFinding]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        findings.append(ManifestFinding("INVALID_OBJECT", path, "expected object"))
        return {}
    return value


def _validate_manifest(
    manifest: Mapping[str, Any],
    *,
    package: str,
    root: Path,
    domain_ids: set[str],
    benchmark_ids: set[str],
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, tuple[ManifestFinding, ...]]:
    findings: list[ManifestFinding] = []
    base = f"research/reproductions/{package}/manifest.json"
    expected_keys = {
        "schema",
        "package",
        "discovery",
        "program_method",
        "source_cuts",
        "scientific_tests",
    }
    if set(manifest) != expected_keys:
        findings.append(ManifestFinding("MANIFEST_SHAPE_MISMATCH", base, f"expected keys {sorted(expected_keys)}"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        findings.append(ManifestFinding("MANIFEST_SCHEMA_MISMATCH", f"{base}.schema", MANIFEST_SCHEMA))
    if manifest.get("package") != package:
        findings.append(ManifestFinding("PACKAGE_IDENTITY_MISMATCH", f"{base}.package", package))

    discovery = _object(manifest.get("discovery"), f"{base}.discovery", findings)
    if discovery and set(discovery) != {"id", "year", "source", "domains"}:
        findings.append(ManifestFinding("DISCOVERY_SHAPE_MISMATCH", f"{base}.discovery", "expected id/year/source/domains"))
    discovery_id = _token(discovery.get("id"), f"{base}.discovery.id", findings)
    year = discovery.get("year")
    if type(year) is not int or year < 1950 or year > 2100:
        findings.append(ManifestFinding("INVALID_YEAR", f"{base}.discovery.year", repr(year)))
    discovery_source = _https(discovery.get("source"), f"{base}.discovery.source", findings)
    domains = _string_list(discovery.get("domains"), f"{base}.discovery.domains", findings, non_empty=True)
    for domain in domains:
        if domain not in domain_ids:
            findings.append(ManifestFinding("UNKNOWN_DISCOVERY_DOMAIN", f"{base}.discovery.domains", domain))

    method = _object(manifest.get("program_method"), f"{base}.program_method", findings)
    expected_method_keys = {
        "method_id",
        "title",
        "year",
        "paper_uri",
        "reference_repositories",
        "families",
        "reproduction_status",
        "priority",
        "benchmark_ids",
        "platform_pressure",
        "method_owned",
        "platform_owned",
        "evidence_refs",
    }
    if method and set(method) != expected_method_keys:
        findings.append(ManifestFinding("PROGRAM_METHOD_SHAPE_MISMATCH", f"{base}.program_method", f"expected keys {sorted(expected_method_keys)}"))
    method_id = _token(method.get("method_id"), f"{base}.program_method.method_id", findings)
    _text(method.get("title"), f"{base}.program_method.title", findings)
    if method.get("year") != year:
        findings.append(ManifestFinding("METHOD_YEAR_MISMATCH", f"{base}.program_method.year", "must equal discovery year"))
    paper_uri = _https(method.get("paper_uri"), f"{base}.program_method.paper_uri", findings)
    if paper_uri and discovery_source and paper_uri != discovery_source:
        findings.append(ManifestFinding("PAPER_SOURCE_MISMATCH", f"{base}.program_method.paper_uri", "must equal discovery source"))
    repositories = _string_list(method.get("reference_repositories"), f"{base}.program_method.reference_repositories", findings, non_empty=True)
    for repository in repositories:
        if not repository.startswith("https://"):
            findings.append(ManifestFinding("NON_HTTPS_REPOSITORY", f"{base}.program_method.reference_repositories", repository))
    _string_list(method.get("families"), f"{base}.program_method.families", findings, non_empty=True)
    status = method.get("reproduction_status")
    if status not in _ALLOWED_REPRODUCTION_STATUS:
        findings.append(ManifestFinding("INVALID_REPRODUCTION_STATUS", f"{base}.program_method.reproduction_status", repr(status)))
    priority = method.get("priority")
    if type(priority) is not int or priority <= 0:
        findings.append(ManifestFinding("INVALID_PRIORITY", f"{base}.program_method.priority", repr(priority)))
    benchmarks = _string_list(method.get("benchmark_ids"), f"{base}.program_method.benchmark_ids", findings)
    for benchmark in benchmarks:
        if benchmark not in benchmark_ids:
            findings.append(ManifestFinding("UNKNOWN_BENCHMARK", f"{base}.program_method.benchmark_ids", benchmark))
    _string_list(method.get("platform_pressure"), f"{base}.program_method.platform_pressure", findings, non_empty=True)
    _string_list(method.get("method_owned"), f"{base}.program_method.method_owned", findings, non_empty=True)
    _string_list(method.get("platform_owned"), f"{base}.program_method.platform_owned", findings, non_empty=True)
    _string_list(method.get("evidence_refs"), f"{base}.program_method.evidence_refs", findings)
    if discovery_id and method_id and discovery_id != method_id:
        findings.append(ManifestFinding("METHOD_DISCOVERY_ID_MISMATCH", base, f"{discovery_id} != {method_id}"))

    cuts = manifest.get("source_cuts")
    if not isinstance(cuts, list) or not cuts or any(not isinstance(item, Mapping) for item in cuts):
        findings.append(ManifestFinding("INVALID_SOURCE_CUTS", f"{base}.source_cuts", "expected non-empty object list"))
    else:
        seen_cuts: set[tuple[str, str]] = set()
        for index, cut in enumerate(cuts):
            cut_path = f"{base}.source_cuts[{index}]"
            if set(cut) != {"repository", "commit"}:
                findings.append(ManifestFinding("SOURCE_CUT_SHAPE_MISMATCH", cut_path, "expected repository/commit"))
            repository = _https(cut.get("repository"), f"{cut_path}.repository", findings)
            commit = _text(cut.get("commit"), f"{cut_path}.commit", findings)
            if commit and not _SHA40.fullmatch(commit):
                findings.append(ManifestFinding("INVALID_SOURCE_COMMIT", f"{cut_path}.commit", commit))
            if repository and commit:
                identity = (repository, commit)
                if identity in seen_cuts:
                    findings.append(ManifestFinding("DUPLICATE_SOURCE_CUT", cut_path, f"{repository}@{commit}"))
                seen_cuts.add(identity)

    tests = _string_list(manifest.get("scientific_tests"), f"{base}.scientific_tests", findings, non_empty=True)
    for test in tests:
        if not test.startswith("tests/test_scientific_") or not test.endswith(".py"):
            findings.append(ManifestFinding("NON_SCIENTIFIC_TEST_BINDING", f"{base}.scientific_tests", test))
        if not (root / test).is_file():
            findings.append(ManifestFinding("MISSING_SCIENTIFIC_TEST", f"{base}.scientific_tests", test))

    return (discovery if discovery else None), (method if method else None), tuple(findings)


def _array_object_spans(text: str, key: str) -> tuple[int, int, tuple[tuple[int, int], ...]]:
    marker = json.dumps(key)
    marker_pos = text.find(marker)
    if marker_pos < 0:
        raise ValueError(f"JSON document is missing {key!r}")
    array_start = text.find("[", marker_pos + len(marker))
    if array_start < 0:
        raise ValueError(f"JSON field {key!r} is not an array")

    spans: list[tuple[int, int]] = []
    bracket_depth = 1
    brace_depth = 0
    object_start: int | None = None
    in_string = False
    escaped = False
    index = array_start + 1
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
            if bracket_depth == 0:
                return array_start, index, tuple(spans)
        elif char == "{":
            if bracket_depth == 1 and brace_depth == 0:
                object_start = index
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if brace_depth < 0:
                raise ValueError(f"unbalanced object braces in {key!r}")
            if bracket_depth == 1 and brace_depth == 0 and object_start is not None:
                spans.append((object_start, index + 1))
                object_start = None
        index += 1
    raise ValueError(f"unterminated JSON array {key!r}")


def _project_array_objects(
    text: str,
    *,
    key: str,
    id_field: str,
    desired: Mapping[str, Mapping[str, Any]],
) -> str:
    array_start, array_end, spans = _array_object_spans(text, key)
    existing: dict[str, tuple[int, int, Mapping[str, Any]]] = {}
    for start, end in spans:
        row = json.loads(text[start:end])
        if not isinstance(row, Mapping):
            raise TypeError(f"{key} must contain only objects")
        identity = row.get(id_field)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"{key} object is missing {id_field}")
        if identity in existing:
            raise ValueError(f"duplicate {key}.{id_field}: {identity}")
        existing[identity] = (start, end, row)

    edits: list[tuple[int, int, str]] = []
    for identity, row in desired.items():
        if identity not in existing:
            continue
        start, end, current = existing[identity]
        if dict(current) != dict(row):
            edits.append((start, end, json.dumps(row, ensure_ascii=False, separators=(",", ":"))))

    missing = [row for identity, row in sorted(desired.items()) if identity not in existing]
    if missing:
        insert_at = array_end
        while insert_at > array_start + 1 and text[insert_at - 1].isspace():
            insert_at -= 1
        prefix = ",\n    " if spans else "\n    "
        payload = prefix + ",\n    ".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in missing
        )
        edits.append((insert_at, insert_at, payload))

    result = text
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _load_policy(root: Path, findings: list[ManifestFinding]) -> tuple[str, ...]:
    path = root / "research/catalog/reproduction_manifest_policy.json"
    policy = _load_object(path)
    if policy.get("schema") != POLICY_SCHEMA:
        findings.append(ManifestFinding("POLICY_SCHEMA_MISMATCH", str(path.relative_to(root)), POLICY_SCHEMA))
    if policy.get("manifest_schema") != MANIFEST_SCHEMA or policy.get("manifest_filename") != "manifest.json":
        findings.append(ManifestFinding("POLICY_MANIFEST_CONTRACT_MISMATCH", str(path.relative_to(root)), MANIFEST_SCHEMA))
    legacy = _string_list(policy.get("legacy_unmanifested_packages"), "reproduction_manifest_policy.legacy_unmanifested_packages", findings)
    if tuple(sorted(legacy)) != legacy:
        findings.append(ManifestFinding("LEGACY_LIST_NOT_SORTED", "reproduction_manifest_policy.legacy_unmanifested_packages", "must be sorted"))
    if not set(legacy).issubset(_INITIAL_LEGACY_PACKAGES):
        findings.append(ManifestFinding("LEGACY_ALLOWLIST_GROWTH", "reproduction_manifest_policy.legacy_unmanifested_packages", "legacy set may shrink but may never gain a new package"))
    return legacy


def project(root: Path) -> tuple[str, str, tuple[ManifestFinding, ...], Mapping[str, Any]]:
    findings: list[ManifestFinding] = []
    scope_path = root / "research/catalog/agent_reproduction_scope.json"
    program_path = root / "research/catalog/research_program.json"
    scope = _load_object(scope_path)
    program = _load_object(program_path)
    if scope.get("schema") != SCOPE_SCHEMA:
        findings.append(ManifestFinding("SCOPE_SCHEMA_MISMATCH", str(scope_path.relative_to(root)), SCOPE_SCHEMA))
    if program.get("schema") != PROGRAM_SCHEMA:
        findings.append(ManifestFinding("PROGRAM_SCHEMA_MISMATCH", str(program_path.relative_to(root)), PROGRAM_SCHEMA))

    domains = scope.get("required_domains")
    domain_ids = {
        row.get("domain_id")
        for row in domains
        if isinstance(domains, list) and isinstance(row, Mapping) and isinstance(row.get("domain_id"), str)
    } if isinstance(domains, list) else set()
    benchmarks = program.get("benchmarks")
    benchmark_ids = {
        row.get("benchmark_id")
        for row in benchmarks
        if isinstance(benchmarks, list) and isinstance(row, Mapping) and isinstance(row.get("benchmark_id"), str)
    } if isinstance(benchmarks, list) else set()

    legacy = set(_load_policy(root, findings))
    reproductions_root = root / "research/reproductions"
    packages = tuple(sorted(path.name for path in reproductions_root.iterdir() if path.is_dir() and not path.name.startswith("__")))
    missing_legacy = sorted(legacy - set(packages))
    for package in missing_legacy:
        findings.append(ManifestFinding("STALE_LEGACY_PACKAGE", "reproduction_manifest_policy.legacy_unmanifested_packages", package))

    discoveries: dict[str, Mapping[str, Any]] = {}
    methods: dict[str, Mapping[str, Any]] = {}
    manifest_packages: list[str] = []
    for package in packages:
        manifest_path = reproductions_root / package / "manifest.json"
        if not manifest_path.is_file():
            if package not in legacy:
                findings.append(ManifestFinding("MISSING_REPRODUCTION_MANIFEST", str(manifest_path.relative_to(root)), "new reproduction packages must be manifested"))
            continue
        if package in legacy:
            findings.append(ManifestFinding("STALE_LEGACY_ALLOWANCE", "reproduction_manifest_policy.legacy_unmanifested_packages", f"remove migrated package {package}"))
        manifest_packages.append(package)
        manifest = _load_object(manifest_path)
        discovery, method, manifest_findings = _validate_manifest(
            manifest,
            package=package,
            root=root,
            domain_ids=domain_ids,
            benchmark_ids=benchmark_ids,
        )
        findings.extend(manifest_findings)
        if discovery is not None:
            identity = discovery.get("id")
            if isinstance(identity, str):
                if identity in discoveries:
                    findings.append(ManifestFinding("DUPLICATE_MANIFEST_METHOD", str(manifest_path.relative_to(root)), identity))
                discoveries[identity] = discovery
        if method is not None:
            identity = method.get("method_id")
            if isinstance(identity, str):
                if identity in methods:
                    findings.append(ManifestFinding("DUPLICATE_MANIFEST_METHOD", str(manifest_path.relative_to(root)), identity))
                methods[identity] = method

    scope_text = scope_path.read_text(encoding="utf-8")
    program_text = program_path.read_text(encoding="utf-8")
    projected_scope = _project_array_objects(scope_text, key="seed_lineages", id_field="id", desired=discoveries)
    projected_program = _project_array_objects(program_text, key="methods", id_field="method_id", desired=methods)
    report = {
        "schema": MANIFEST_SCHEMA,
        "package_count": len(packages),
        "manifest_package_count": len(manifest_packages),
        "legacy_unmanifested_count": len(legacy),
        "projected_discovery_count": len(discoveries),
        "projected_method_count": len(methods),
        "scope_drift": projected_scope != scope_text,
        "program_drift": projected_program != program_text,
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    return projected_scope, projected_program, tuple(findings), report


def sync_reproduction_manifests(root: Path, *, check: bool) -> tuple[ManifestFinding, ...]:
    projected_scope, projected_program, findings, report = project(root)
    if findings:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return findings

    scope_path = root / "research/catalog/agent_reproduction_scope.json"
    program_path = root / "research/catalog/research_program.json"
    scope_text = scope_path.read_text(encoding="utf-8")
    program_text = program_path.read_text(encoding="utf-8")
    drift_findings: list[ManifestFinding] = []
    if check:
        if projected_scope != scope_text:
            drift_findings.append(ManifestFinding("REPRODUCTION_SCOPE_MANIFEST_DRIFT", str(scope_path.relative_to(root)), "run scripts/sync_reproduction_manifests.py"))
        if projected_program != program_text:
            drift_findings.append(ManifestFinding("RESEARCH_PROGRAM_MANIFEST_DRIFT", str(program_path.relative_to(root)), "run scripts/sync_reproduction_manifests.py"))
    else:
        if projected_scope != scope_text:
            scope_path.write_text(projected_scope, encoding="utf-8")
        if projected_program != program_text:
            program_path.write_text(projected_program, encoding="utf-8")

    report = dict(report)
    report["finding_count"] = len(drift_findings)
    report["findings"] = [asdict(finding) for finding in drift_findings]
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return tuple(drift_findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project package-local reproduction manifests into the canonical discovery scope and research program.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings = sync_reproduction_manifests(args.root.resolve(), check=args.check)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
