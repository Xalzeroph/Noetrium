from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from noetrium_platform.foundation.governance.api import (
    GovernanceBaselineApproval,
    GovernanceBaselineApprovalSet,
    GovernanceBaselineLane,
)

_SET_SCHEMA = "governance-baseline-approval-set.v1"
_RECORD_SCHEMA = "governance-baseline-approval.v1"
_SCOPE = "governance-baseline-refresh"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{5,127}")


class GovernanceBaselineApprovalError(RuntimeError):
    pass


def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GovernanceBaselineApprovalError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return text


def _git_sha(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be exact lowercase 40-character Git SHA")
    return text


def _record_digest(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "approval_record_sha256"}
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _decode_record(value: dict[str, object], *, index: int) -> GovernanceBaselineApproval:
    expected = {
        "schema", "approval_id", "lane", "source_sha", "source_digest", "analyzer_revision",
        "analyzer_implementation_digest", "baseline_digest", "decision", "authority", "scope",
        "review_state", "review_evidence_refs", "issued_at", "note", "approval_record_sha256",
    }
    if set(value) != expected or value["schema"] != _RECORD_SCHEMA:
        raise ValueError(f"approvals[{index}] has unexpected fields or schema")
    approval_id = _text(value["approval_id"], field=f"approvals[{index}].approval_id")
    if _ID_RE.fullmatch(approval_id) is None:
        raise ValueError(f"approvals[{index}].approval_id is not canonical")
    try:
        lane = GovernanceBaselineLane(_text(value["lane"], field=f"approvals[{index}].lane"))
    except ValueError as exc:
        raise ValueError(f"approvals[{index}].lane is unsupported") from exc
    decision = _text(value["decision"], field=f"approvals[{index}].decision")
    if decision not in {"approved", "not_approved"}:
        raise ValueError(f"approvals[{index}].decision is invalid")
    if value["authority"] != "ROLE00" or value["scope"] != _SCOPE:
        raise ValueError(f"approvals[{index}] authority/scope is invalid")
    refs = value["review_evidence_refs"]
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError(f"approvals[{index}].review_evidence_refs must be non-empty strings")
    observed = _sha(value["approval_record_sha256"], field=f"approvals[{index}].approval_record_sha256")
    if _record_digest(value) != observed:
        raise GovernanceBaselineApprovalError(f"approval record digest mismatch: {approval_id}")
    return GovernanceBaselineApproval(
        approval_id=approval_id,
        lane=lane,
        source_git_sha=_git_sha(value["source_sha"], field=f"approvals[{index}].source_sha"),
        source_digest=_sha(value["source_digest"], field=f"approvals[{index}].source_digest"),
        analyzer_revision=_text(value["analyzer_revision"], field=f"approvals[{index}].analyzer_revision"),
        analyzer_implementation_digest=_sha(
            value["analyzer_implementation_digest"],
            field=f"approvals[{index}].analyzer_implementation_digest",
        ),
        baseline_digest=_sha(value["baseline_digest"], field=f"approvals[{index}].baseline_digest"),
        decision=decision,
        authority="ROLE00",
        scope=_SCOPE,
        review_state=_text(value["review_state"], field=f"approvals[{index}].review_state"),
        review_evidence_refs=tuple(refs),
        issued_at=_text(value["issued_at"], field=f"approvals[{index}].issued_at"),
        note=_text(value["note"], field=f"approvals[{index}].note"),
        approval_record_sha256=observed,
    )


def load_governance_baseline_approval_set(
    path: Path,
    *,
    expected_sha256: str,
) -> GovernanceBaselineApprovalSet:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise GovernanceBaselineApprovalError(f"governance baseline approval set unavailable: {source}") from exc
    expected = _sha(expected_sha256, field="approval set SHA-256")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise GovernanceBaselineApprovalError(
            f"approval set digest mismatch: observed={observed} expected={expected}"
        )
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GovernanceBaselineApprovalError("governance baseline approval set is not strict JSON") from exc
    expected_fields = {"schema", "authority", "approvals", "default_decision", "rule"}
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError("governance baseline approval set has unexpected fields")
    if document["schema"] != _SET_SCHEMA or document["authority"] != "ROLE00":
        raise ValueError("unsupported governance baseline approval authority")
    if document["default_decision"] != "not_approved":
        raise ValueError("governance baseline approval default_decision must be not_approved")
    raw_records = document["approvals"]
    if not isinstance(raw_records, list):
        raise ValueError("governance baseline approvals must be an array")
    approvals = tuple(_decode_record(item, index=index) for index, item in enumerate(raw_records) if isinstance(item, dict))
    if len(approvals) != len(raw_records):
        raise ValueError("governance baseline approval records must be objects")
    ids = tuple(row.approval_id for row in approvals)
    if len(ids) != len(set(ids)):
        raise ValueError("governance baseline approval ids must be unique")
    return GovernanceBaselineApprovalSet(
        schema_version=_SET_SCHEMA,
        authority="ROLE00",
        approvals=approvals,
        default_decision="not_approved",
        rule=_text(document["rule"], field="approval set rule"),
    )


__all__ = [
    "GovernanceBaselineApprovalError",
    "load_governance_baseline_approval_set",
]
