from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "noetrium.research-program.v1"
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
REPRODUCTION_STATES = frozenset({"queued", "scaffolded", "pilot", "matched", "blocked", "retired"})
GAP_STATES = frozenset({"candidate", "active", "absorbed", "rejected"})
INNOVATION_STATES = frozenset({"idea", "scaffolded", "pilot", "running", "analysis", "claim_ready", "retired"})
PROMOTION_REASONS = frozenset({
    "shared_by_multiple_methods",
    "cross_cutting_runtime_invariant",
    "required_for_reproducibility",
})


@dataclass(frozen=True, slots=True)
class ResearchProgramFinding:
    code: str
    path: str
    detail: str


class ResearchProgramValidationError(ValueError):
    def __init__(self, findings: tuple[ResearchProgramFinding, ...]) -> None:
        super().__init__("research program validation failed: " + "; ".join(
            f"{row.code}@{row.path}: {row.detail}" for row in findings
        ))
        self.findings = findings


def _text(value: object, path: str, findings: list[ResearchProgramFinding]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        findings.append(ResearchProgramFinding("INVALID_TEXT", path, "expected canonical non-empty text"))
        return ""
    return value


def _token(value: object, path: str, findings: list[ResearchProgramFinding]) -> str:
    text = _text(value, path, findings)
    if text and not _TOKEN.fullmatch(text):
        findings.append(ResearchProgramFinding("INVALID_TOKEN", path, text))
    return text


def _string_tuple(value: object, path: str, findings: list[ResearchProgramFinding], *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        findings.append(ResearchProgramFinding("INVALID_STRING_LIST", path, "expected a list of non-empty strings"))
        return ()
    rows = tuple(value)
    if nonempty and not rows:
        findings.append(ResearchProgramFinding("EMPTY_STRING_LIST", path, "at least one item is required"))
    if len(rows) != len(set(rows)):
        findings.append(ResearchProgramFinding("DUPLICATE_LIST_ITEM", path, "items must be unique"))
    return rows


def _objects(value: object, path: str, findings: list[ResearchProgramFinding]) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        findings.append(ResearchProgramFinding("INVALID_OBJECT_LIST", path, "expected a list of objects"))
        return ()
    return tuple(value)


def _unique_ids(rows: tuple[Mapping[str, Any], ...], field: str, path: str, findings: list[ResearchProgramFinding]) -> set[str]:
    ids: list[str] = []
    for index, row in enumerate(rows):
        ids.append(_token(row.get(field), f"{path}[{index}].{field}", findings))
    valid = [value for value in ids if value]
    if len(valid) != len(set(valid)):
        findings.append(ResearchProgramFinding("DUPLICATE_ID", path, f"{field} values must be unique"))
    return set(valid)


def validate_research_program(document: Mapping[str, Any], registry: Mapping[str, Any]) -> tuple[ResearchProgramFinding, ...]:
    findings: list[ResearchProgramFinding] = []
    if document.get("schema") != SCHEMA:
        findings.append(ResearchProgramFinding("SCHEMA_MISMATCH", "schema", f"expected {SCHEMA}"))
    policy = document.get("policy")
    if not isinstance(policy, Mapping):
        findings.append(ResearchProgramFinding("POLICY_REQUIRED", "policy", "policy must be an object"))
        policy = {}
    if policy.get("external_repositories_are_runtime_dependencies") is not False:
        findings.append(ResearchProgramFinding(
            "EXTERNAL_RUNTIME_DEPENDENCY_FORBIDDEN", "policy.external_repositories_are_runtime_dependencies",
            "external repositories are research references only",
        ))
    promotion = _string_tuple(policy.get("platform_promotion_reasons", []), "policy.platform_promotion_reasons", findings, nonempty=True)
    unknown_promotion = sorted(set(promotion) - PROMOTION_REASONS)
    if unknown_promotion:
        findings.append(ResearchProgramFinding("UNKNOWN_PROMOTION_REASON", "policy.platform_promotion_reasons", ", ".join(unknown_promotion)))

    methods = _objects(document.get("methods"), "methods", findings)
    benchmarks = _objects(document.get("benchmarks"), "benchmarks", findings)
    gaps = _objects(document.get("platform_gaps"), "platform_gaps", findings)
    innovations = _objects(document.get("innovation_tracks"), "innovation_tracks", findings)
    constraints = _objects(document.get("project_constraints", []), "project_constraints", findings)
    method_ids = _unique_ids(methods, "method_id", "methods", findings)
    benchmark_ids = _unique_ids(benchmarks, "benchmark_id", "benchmarks", findings)
    _unique_ids(gaps, "gap_id", "platform_gaps", findings)
    innovation_ids = _unique_ids(innovations, "innovation_id", "innovation_tracks", findings)
    registry_keys = set(registry)

    for index, row in enumerate(methods):
        base = f"methods[{index}]"
        _text(row.get("title"), f"{base}.title", findings)
        paper_uri = _text(row.get("paper_uri"), f"{base}.paper_uri", findings)
        if paper_uri and not paper_uri.startswith("https://"):
            findings.append(ResearchProgramFinding("NON_HTTPS_SOURCE", f"{base}.paper_uri", paper_uri))
        year = row.get("year")
        if type(year) is not int or year < 2000 or year > 2100:
            findings.append(ResearchProgramFinding("INVALID_YEAR", f"{base}.year", repr(year)))
        _string_tuple(row.get("families"), f"{base}.families", findings, nonempty=True)
        references = _string_tuple(row.get("reference_repositories", []), f"{base}.reference_repositories", findings)
        if any(not ref.startswith("https://github.com/") for ref in references):
            findings.append(ResearchProgramFinding("INVALID_REPOSITORY_REFERENCE", f"{base}.reference_repositories", "references must be GitHub HTTPS URLs"))
        status = row.get("reproduction_status")
        if status not in REPRODUCTION_STATES:
            findings.append(ResearchProgramFinding("INVALID_REPRODUCTION_STATE", f"{base}.reproduction_status", repr(status)))
        priority = row.get("priority")
        if type(priority) is not int or priority < 1:
            findings.append(ResearchProgramFinding("INVALID_PRIORITY", f"{base}.priority", repr(priority)))
        method_benchmarks = _string_tuple(row.get("benchmark_ids", []), f"{base}.benchmark_ids", findings)
        for benchmark_id in method_benchmarks:
            if benchmark_id not in benchmark_ids:
                findings.append(ResearchProgramFinding("UNKNOWN_BENCHMARK", f"{base}.benchmark_ids", benchmark_id))
        pressure = _string_tuple(row.get("platform_pressure"), f"{base}.platform_pressure", findings, nonempty=True)
        for system_key in pressure:
            if system_key not in registry_keys:
                findings.append(ResearchProgramFinding("UNKNOWN_PLATFORM_SYSTEM", f"{base}.platform_pressure", system_key))
        _string_tuple(row.get("method_owned"), f"{base}.method_owned", findings, nonempty=True)
        _string_tuple(row.get("platform_owned"), f"{base}.platform_owned", findings, nonempty=True)
        evidence = _string_tuple(row.get("evidence_refs", []), f"{base}.evidence_refs", findings)
        if status == "matched" and not evidence:
            findings.append(ResearchProgramFinding("MATCHED_WITHOUT_EVIDENCE", f"{base}.evidence_refs", "matched reproductions require evidence refs"))

    for index, row in enumerate(benchmarks):
        base = f"benchmarks[{index}]"
        _text(row.get("title"), f"{base}.title", findings)
        uri = _text(row.get("source_uri"), f"{base}.source_uri", findings)
        if uri and not uri.startswith("https://"):
            findings.append(ResearchProgramFinding("NON_HTTPS_SOURCE", f"{base}.source_uri", uri))
        _string_tuple(row.get("environment_kinds"), f"{base}.environment_kinds", findings, nonempty=True)

    for index, row in enumerate(gaps):
        base = f"platform_gaps[{index}]"
        status = row.get("status")
        if status not in GAP_STATES:
            findings.append(ResearchProgramFinding("INVALID_GAP_STATE", f"{base}.status", repr(status)))
        reason = row.get("promotion_reason")
        if reason not in PROMOTION_REASONS:
            findings.append(ResearchProgramFinding("INVALID_PROMOTION_REASON", f"{base}.promotion_reason", repr(reason)))
        triggers = _string_tuple(row.get("trigger_method_ids"), f"{base}.trigger_method_ids", findings, nonempty=True)
        for method_id in triggers:
            if method_id not in method_ids:
                findings.append(ResearchProgramFinding("UNKNOWN_METHOD", f"{base}.trigger_method_ids", method_id))
        targets = _string_tuple(row.get("target_systems"), f"{base}.target_systems", findings, nonempty=True)
        for system_key in targets:
            if system_key not in registry_keys:
                findings.append(ResearchProgramFinding("UNKNOWN_PLATFORM_SYSTEM", f"{base}.target_systems", system_key))
        _text(row.get("problem"), f"{base}.problem", findings)

    for index, row in enumerate(constraints):
        base = f"project_constraints[{index}]"
        _token(row.get("project_id"), f"{base}.project_id", findings)
        _text(row.get("reason"), f"{base}.reason", findings)
        forbidden = _objects(row.get("forbidden_method_features"), f"{base}.forbidden_method_features", findings)
        if not forbidden:
            findings.append(ResearchProgramFinding("EMPTY_PROJECT_CONSTRAINT", f"{base}.forbidden_method_features", "at least one forbidden method feature set is required"))
        for item_index, item in enumerate(forbidden):
            item_base = f"{base}.forbidden_method_features[{item_index}]"
            method_id = _token(item.get("method_id"), f"{item_base}.method_id", findings)
            if method_id and method_id not in method_ids:
                findings.append(ResearchProgramFinding("UNKNOWN_METHOD", f"{item_base}.method_id", method_id))
            _string_tuple(item.get("features"), f"{item_base}.features", findings, nonempty=True)

    for index, row in enumerate(innovations):
        base = f"innovation_tracks[{index}]"
        status = row.get("status")
        if status not in INNOVATION_STATES:
            findings.append(ResearchProgramFinding("INVALID_INNOVATION_STATE", f"{base}.status", repr(status)))
        parents = _string_tuple(row.get("parent_method_ids"), f"{base}.parent_method_ids", findings)
        for method_id in parents:
            if method_id not in method_ids:
                findings.append(ResearchProgramFinding("UNKNOWN_METHOD", f"{base}.parent_method_ids", method_id))
        _text(row.get("downstream_project"), f"{base}.downstream_project", findings)
        _text(row.get("scientific_boundary"), f"{base}.scientific_boundary", findings)
        blocked_by = _string_tuple(row.get("blocked_by_innovation_ids", []), f"{base}.blocked_by_innovation_ids", findings)
        for innovation_id in blocked_by:
            if innovation_id not in innovation_ids:
                findings.append(ResearchProgramFinding("UNKNOWN_INNOVATION", f"{base}.blocked_by_innovation_ids", innovation_id))

    return tuple(findings)


def load_and_validate(root: Path) -> Mapping[str, Any]:
    program_path = root / "research/catalog/research_program.json"
    registry_path = root / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    document = json.loads(program_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or not isinstance(registry, Mapping):
        raise TypeError("research program and system registry must be JSON objects")
    findings = validate_research_program(document, registry)
    if findings:
        raise ResearchProgramValidationError(findings)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        document = load_and_validate(args.root.resolve())
    except ResearchProgramValidationError as exc:
        print(json.dumps({
            "schema": SCHEMA,
            "valid": False,
            "finding_count": len(exc.findings),
            "findings": [asdict(row) for row in exc.findings],
        }, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps({
        "schema": SCHEMA,
        "valid": True,
        "method_count": len(document["methods"]),
        "benchmark_count": len(document["benchmarks"]),
        "platform_gap_count": len(document["platform_gaps"]),
        "innovation_count": len(document["innovation_tracks"]),
        "project_constraint_count": len(document.get("project_constraints", [])),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())