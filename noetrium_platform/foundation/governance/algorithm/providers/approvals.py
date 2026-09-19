from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from noetrium_platform.foundation.governance.algorithm.api import (
    AlgorithmBaselineApproval,
    AlgorithmComplexityMigrationApproval,
    AlgorithmGovernanceApprovalSet,
)

_APPROVAL_SET_SCHEMA = "algorithm-governance-approval-set.v1"
_BASELINE_SCHEMA = "algorithm-baseline-approval.v1"
_COMPLEXITY_SCHEMA = "algorithm-complexity-migration-approval.v1"
_BASELINE_SCOPE = "algorithm-baseline-refresh"
_COMPLEXITY_SCOPE = "algorithm-complexity-lower-bound"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{5,127}")
_COMPLEXITIES = frozenset({"O(1)", "O(N)", "O(N log N)", "O(N^2)", "O(N^3+)", "recursive+iterative"})


class AlgorithmGovernanceApprovalError(RuntimeError):
    pass


def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AlgorithmGovernanceApprovalError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _canonical_sha(value: object, *, field: str) -> str:
    text = _required_text(value, field=field)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return text


def _canonical_git_sha(value: object, *, field: str) -> str:
    text = _required_text(value, field=field)
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be exact lowercase 40-character Git SHA")
    return text


def _record_digest(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "approval_record_sha256"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _common(value: dict[str, object], *, index: int, expected_scope: str) -> dict[str, object]:
    approval_id = _required_text(
        value.get("approval_id", value.get("migration_id", "")),
        field=f"approvals[{index}] id",
    )
    if _ID_RE.fullmatch(approval_id) is None:
        raise ValueError(f"approvals[{index}] id is not canonical")
    decision = _required_text(value["decision"], field=f"approvals[{index}].decision")
    if decision not in {"approved", "not_approved"}:
        raise ValueError(f"approvals[{index}].decision is invalid")
    if value["authority"] != "ROLE00":
        raise ValueError(f"approvals[{index}].authority must be ROLE00")
    if value["scope"] != expected_scope:
        raise ValueError(f"approvals[{index}].scope must be {expected_scope}")
    refs = value["review_evidence_refs"]
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError(f"approvals[{index}].review_evidence_refs must be non-empty strings")
    observed = _canonical_sha(value["approval_record_sha256"], field=f"approvals[{index}].approval_record_sha256")
    if _record_digest(value) != observed:
        raise AlgorithmGovernanceApprovalError(f"approval record digest mismatch: {approval_id}")
    return {
        "source_git_sha": _canonical_git_sha(value["source_sha"], field=f"approvals[{index}].source_sha"),
        "source_digest": _canonical_sha(value["source_digest"], field=f"approvals[{index}].source_digest"),
        "analyzer_revision": _required_text(value["analyzer_revision"], field=f"approvals[{index}].analyzer_revision"),
        "analyzer_implementation_digest": _canonical_sha(value["analyzer_implementation_digest"], field=f"approvals[{index}].analyzer_implementation_digest"),
        "decision": decision,
        "authority": "ROLE00",
        "scope": expected_scope,
        "review_state": _required_text(value["review_state"], field=f"approvals[{index}].review_state"),
        "review_evidence_refs": tuple(refs),
        "issued_at": _required_text(value["issued_at"], field=f"approvals[{index}].issued_at"),
        "approval_record_sha256": observed,
    }


def _decode_baseline(value: dict[str, object], *, index: int) -> AlgorithmBaselineApproval:
    expected = {
        "schema", "approval_id", "source_sha", "source_digest", "analyzer_revision",
        "analyzer_implementation_digest", "snapshot_digest", "decision", "authority", "scope",
        "review_state", "review_evidence_refs", "issued_at", "note", "approval_record_sha256",
    }
    if set(value) != expected:
        raise ValueError(f"approvals[{index}] baseline record has unexpected fields")
    common = _common(value, index=index, expected_scope=_BASELINE_SCOPE)
    return AlgorithmBaselineApproval(
        approval_id=_required_text(value["approval_id"], field=f"approvals[{index}].approval_id"),
        snapshot_digest=_canonical_sha(value["snapshot_digest"], field=f"approvals[{index}].snapshot_digest"),
        note=_required_text(value["note"], field=f"approvals[{index}].note"),
        **common,
    )


def _decode_complexity(value: dict[str, object], *, index: int) -> AlgorithmComplexityMigrationApproval:
    expected = {
        "schema", "migration_id", "symbol_id", "source_sha", "source_digest", "analyzer_revision",
        "analyzer_implementation_digest", "old_complexity", "new_complexity", "decision", "authority",
        "scope", "review_state", "review_evidence_refs", "issued_at", "rationale", "approval_record_sha256",
    }
    if set(value) != expected:
        raise ValueError(f"approvals[{index}] complexity record has unexpected fields")
    old = _required_text(value["old_complexity"], field=f"approvals[{index}].old_complexity")
    new = _required_text(value["new_complexity"], field=f"approvals[{index}].new_complexity")
    if old not in _COMPLEXITIES or new not in _COMPLEXITIES or old == new:
        raise ValueError(f"approvals[{index}] complexity transition is invalid")
    rationale = _required_text(value["rationale"], field=f"approvals[{index}].rationale").strip()
    if len(rationale) < 48:
        raise ValueError(f"approvals[{index}].rationale must be substantive")
    common = _common(value, index=index, expected_scope=_COMPLEXITY_SCOPE)
    return AlgorithmComplexityMigrationApproval(
        migration_id=_required_text(value["migration_id"], field=f"approvals[{index}].migration_id"),
        symbol_id=_required_text(value["symbol_id"], field=f"approvals[{index}].symbol_id"),
        old_complexity=old,
        new_complexity=new,
        rationale=rationale,
        **common,
    )


def load_algorithm_governance_approval_set(path: Path, *, expected_sha256: str) -> AlgorithmGovernanceApprovalSet:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise AlgorithmGovernanceApprovalError(f"algorithm approval set unavailable: {source}") from exc
    expected = _canonical_sha(expected_sha256, field="approval set SHA-256")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise AlgorithmGovernanceApprovalError(f"approval set digest mismatch: observed={observed} expected={expected}")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_no_duplicates, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AlgorithmGovernanceApprovalError("algorithm approval set is not strict canonical JSON") from exc
    expected_fields = {"schema", "authority", "approvals", "default_decision", "rule"}
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError("algorithm approval set has unexpected fields")
    if document["schema"] != _APPROVAL_SET_SCHEMA or document["authority"] != "ROLE00":
        raise ValueError("unsupported algorithm approval authority")
    if document["default_decision"] != "not_approved":
        raise ValueError("algorithm approval set default_decision must be not_approved")
    raw_records = document["approvals"]
    if not isinstance(raw_records, list):
        raise ValueError("algorithm approval set approvals must be an array")
    baselines: list[AlgorithmBaselineApproval] = []
    migrations: list[AlgorithmComplexityMigrationApproval] = []
    ids: list[str] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            raise ValueError(f"approvals[{index}] must be an object")
        schema = raw_record.get("schema")
        if schema == _BASELINE_SCHEMA:
            record = _decode_baseline(raw_record, index=index); baselines.append(record); ids.append(record.approval_id)
        elif schema == _COMPLEXITY_SCHEMA:
            record = _decode_complexity(raw_record, index=index); migrations.append(record); ids.append(record.migration_id)
        else:
            raise ValueError(f"approvals[{index}] has unsupported schema")
    if len(ids) != len(set(ids)):
        raise ValueError("algorithm approval record ids must be unique")
    return AlgorithmGovernanceApprovalSet(
        schema_version=_APPROVAL_SET_SCHEMA,
        authority="ROLE00",
        baseline_approvals=tuple(baselines),
        complexity_migrations=tuple(migrations),
        default_decision="not_approved",
        rule=_required_text(document["rule"], field="approval set rule"),
    )


__all__ = ["AlgorithmGovernanceApprovalError", "load_algorithm_governance_approval_set"]
