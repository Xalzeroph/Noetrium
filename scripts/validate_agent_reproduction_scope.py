from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

SCOPE_SCHEMA = "noetrium.agent-reproduction-scope.v1"
PROGRAM_SCHEMA = "noetrium.research-program.projection.v3"
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")


@dataclass(frozen=True, slots=True)
class ScopeFinding:
    code: str
    path: str
    detail: str


def _objects(value: object, path: str, findings: list[ScopeFinding]) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        findings.append(ScopeFinding("INVALID_OBJECT_LIST", path, "expected a list of objects"))
        return ()
    return tuple(value)


def _text(value: object, path: str, findings: list[ScopeFinding]) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        findings.append(ScopeFinding("INVALID_TEXT", path, "expected canonical non-empty text"))
        return ""
    return value


def _token(value: object, path: str, findings: list[ScopeFinding]) -> str:
    text = _text(value, path, findings)
    if text and not _TOKEN.fullmatch(text):
        findings.append(ScopeFinding("INVALID_TOKEN", path, text))
    return text


def _unique(rows: tuple[Mapping[str, Any], ...], field: str, path: str, findings: list[ScopeFinding]) -> set[str]:
    values: list[str] = []
    for index, row in enumerate(rows):
        values.append(_token(row.get(field), f"{path}[{index}].{field}", findings))
    values = [value for value in values if value]
    if len(values) != len(set(values)):
        findings.append(ScopeFinding("DUPLICATE_ID", path, f"{field} values must be unique"))
    return set(values)


def _load_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def validate_scope(scope: Mapping[str, Any], program: Mapping[str, Any]) -> tuple[tuple[ScopeFinding, ...], Mapping[str, Any]]:
    findings: list[ScopeFinding] = []
    if scope.get("schema") != SCOPE_SCHEMA:
        findings.append(ScopeFinding("SCHEMA_MISMATCH", "schema", f"expected {SCOPE_SCHEMA}"))
    if scope.get("authority") != "discovery_scope_only":
        findings.append(ScopeFinding("INVALID_AUTHORITY", "authority", "scope must never become reproduction truth"))
    if scope.get("reproduction_authority") != "research/catalog/research_program.json":
        findings.append(ScopeFinding("INVALID_REPRODUCTION_AUTHORITY", "reproduction_authority", "must point at the canonical research program"))
    if scope.get("scope") != "all_agent_related_research":
        findings.append(ScopeFinding("SCOPE_REGRESSION", "scope", "all-agent discovery scope is required"))

    rules = scope.get("rules")
    if not isinstance(rules, Mapping):
        findings.append(ScopeFinding("RULES_REQUIRED", "rules", "rules must be an object"))
        rules = {}
    for key in ("priority_is_not_exclusion", "historical_to_current", "continuous_frontier_intake"):
        if rules.get(key) is not True:
            findings.append(ScopeFinding("SCOPE_REGRESSION", f"rules.{key}", "must remain true"))
    if rules.get("external_repositories_are_references_only") is not True:
        findings.append(ScopeFinding("RUNTIME_DEPENDENCY_REGRESSION", "rules.external_repositories_are_references_only", "external projects are references, not runtime dependencies"))

    domains = _objects(scope.get("required_domains"), "required_domains", findings)
    seeds = _objects(scope.get("seed_lineages"), "seed_lineages", findings)
    domain_ids = _unique(domains, "domain_id", "required_domains", findings)
    seed_ids = _unique(seeds, "id", "seed_lineages", findings)
    if len(domain_ids) < 20:
        findings.append(ScopeFinding("DOMAIN_COVERAGE_TOO_NARROW", "required_domains", "all-agent scope must retain broad cross-domain coverage"))

    used_domains: set[str] = set()
    for index, row in enumerate(domains):
        _text(row.get("title"), f"required_domains[{index}].title", findings)

    for index, row in enumerate(seeds):
        base = f"seed_lineages[{index}]"
        source = _text(row.get("source"), f"{base}.source", findings)
        if source and not source.startswith("https://"):
            findings.append(ScopeFinding("NON_HTTPS_SOURCE", f"{base}.source", source))
        year = row.get("year")
        if type(year) is not int or year < 1950 or year > 2100:
            findings.append(ScopeFinding("INVALID_YEAR", f"{base}.year", repr(year)))
        seed_domains = row.get("domains")
        if not isinstance(seed_domains, list) or not seed_domains or any(not isinstance(item, str) for item in seed_domains):
            findings.append(ScopeFinding("INVALID_DOMAIN_LIST", f"{base}.domains", "expected non-empty string list"))
            continue
        for domain_id in seed_domains:
            if domain_id not in domain_ids:
                findings.append(ScopeFinding("UNKNOWN_DOMAIN", f"{base}.domains", domain_id))
            else:
                used_domains.add(domain_id)

    if program.get("schema") != PROGRAM_SCHEMA:
        findings.append(ScopeFinding("PROGRAM_SCHEMA_MISMATCH", "research_program.schema", f"expected {PROGRAM_SCHEMA}"))
    program_methods = _objects(program.get("methods"), "research_program.methods", findings)
    program_ids = {
        row.get("method_id") for row in program_methods
        if isinstance(row.get("method_id"), str)
    }
    orphans = sorted(program_ids - seed_ids)
    if orphans:
        findings.append(ScopeFinding("PROGRAM_METHOD_OUTSIDE_DISCOVERY_SCOPE", "research_program.methods", ", ".join(orphans)))

    uncovered_domains = sorted(domain_ids - used_domains)
    unpromoted = sorted(seed_ids - program_ids)
    report = {
        "schema": SCOPE_SCHEMA,
        "valid": not findings,
        "required_domain_count": len(domain_ids),
        "seed_lineage_count": len(seed_ids),
        "promoted_reproduction_count": len(program_ids & seed_ids),
        "unpromoted_seed_count": len(unpromoted),
        "unpromoted_seed_ids": unpromoted,
        "uncovered_domain_count": len(uncovered_domains),
        "uncovered_domain_ids": uncovered_domains,
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    return tuple(findings), report


def load_and_validate(root: Path) -> tuple[tuple[ScopeFinding, ...], Mapping[str, Any]]:
    scope = _load_object(root / "research/catalog/agent_reproduction_scope.json")
    program = _load_object(root / "research/catalog/research_program.json")
    return validate_scope(scope, program)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings, report = load_and_validate(args.root.resolve())
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
