from __future__ import annotations

import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.reliability.failure.api import (
    FailureSpec,
    RecoveryAction,
    RiskLevel,
    fingerprint_failure,
)
from noetrium_platform.infrastructure.reliability.forensics.api.crash_bundle_contracts import CRASH_BUNDLE_SCHEMA_VERSION, CrashBundleVerification


def _read_bundle(path: Path) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        descriptor = describe_exception(exc)
        return None, (f"unreadable bundle: {descriptor.error_type}: {descriptor.safe_message}; error_digest={descriptor.error_digest}",)
    if not isinstance(payload, dict):
        return None, ("bundle root must be a JSON object",)
    return payload, ()


def _verify_schema(data: dict[str, object]) -> tuple[str, ...]:
    if int(data.get("schema_version", -1)) == CRASH_BUNDLE_SCHEMA_VERSION:
        return ()
    return (f"unsupported crash bundle schema: {data.get('schema_version')}",)


def _embedded_failure(data: dict[str, object]) -> tuple[dict[str, object], tuple[str, ...]]:
    failure = data.get("failure")
    failure_id = data.get("failure_id")
    if not isinstance(failure, dict):
        return {}, ("failure payload missing or invalid",)
    if failure.get("failure_id") != failure_id:
        return failure, ("failure_id does not match embedded failure",)
    return failure, ()


def _verify_bundle_digest(data: dict[str, object]) -> tuple[str, ...]:
    expected = data.get("bundle_digest")
    base = {key: value for key, value in data.items() if key != "bundle_digest"}
    actual = hashlib.sha256(
        json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return () if expected == actual else ("bundle digest mismatch",)


def _reconstruct_failure_spec(taxonomy: dict[str, object], spec_data: dict[str, object]) -> FailureSpec:
    return FailureSpec(
        str(taxonomy["domain"]),
        str(taxonomy["code"]),
        str(taxonomy["stage"]),
        RecoveryAction(str(spec_data["default_recovery"])),
        RiskLevel(str(spec_data["data_integrity_risk"])),
        RiskLevel(str(spec_data["comparability_risk"])),
        RiskLevel(str(spec_data["scientific_validity_risk"])),
        str(spec_data.get("description") or ""),
        str(spec_data.get("owner") or ""),
        tuple(str(x) for x in (spec_data.get("diagnostic_focus") or ())),
        tuple(str(x) for x in (spec_data.get("operator_checks") or ())),
    )


def _verify_taxonomy(data: dict[str, object], failure: dict[str, object]) -> tuple[str, ...]:
    taxonomy = data.get("taxonomy")
    if not isinstance(taxonomy, dict):
        return ("taxonomy block missing or invalid",)
    errors: list[str] = []
    for key, failure_key in (("domain", "failure_domain"), ("code", "failure_code"), ("stage", "stage")):
        if taxonomy.get(key) != failure.get(failure_key):
            errors.append(f"taxonomy {key} does not match embedded failure")
    if taxonomy.get("envelope_spec_digest") != failure.get("taxonomy_spec_sha256"):
        errors.append("taxonomy envelope digest does not match embedded failure")
    spec_data = taxonomy.get("spec")
    current_digest = taxonomy.get("current_spec_digest")
    if isinstance(spec_data, dict) and current_digest is not None:
        try:
            if _reconstruct_failure_spec(taxonomy, spec_data).digest() != current_digest:
                errors.append("embedded taxonomy spec digest mismatch")
        except (KeyError, ValueError, TypeError) as exc:
            descriptor = describe_exception(exc)
            errors.append(
                f"embedded taxonomy spec invalid: {descriptor.error_type}: "
                f"{descriptor.safe_message}; error_digest={descriptor.error_digest}"
            )
    return tuple(errors)


def _verify_fingerprints(data: dict[str, object], failure: dict[str, object]) -> tuple[str, ...]:
    fingerprints = data.get("fingerprints")
    if not isinstance(fingerprints, dict):
        return ("fingerprints block missing or invalid",)
    if not failure:
        return ()
    computed = fingerprint_failure(failure)
    checks = (
        (fingerprints.get("exact"), computed.fingerprint, "exact failure fingerprint mismatch"),
        (fingerprints.get("family"), computed.family_fingerprint, "family failure fingerprint mismatch"),
        (tuple(fingerprints.get("exact_signature") or ()), computed.signature, "exact failure signature mismatch"),
        (tuple(fingerprints.get("family_signature") or ()), computed.family_signature, "family failure signature mismatch"),
    )
    return tuple(message for actual, expected, message in checks if actual != expected)


def verify_crash_bundle(path: Path) -> CrashBundleVerification:
    data, read_errors = _read_bundle(path)
    if data is None:
        return CrashBundleVerification(str(path), False, read_errors, None, None)

    failure, failure_errors = _embedded_failure(data)
    errors = (
        *_verify_schema(data),
        *failure_errors,
        *_verify_bundle_digest(data),
        *_verify_taxonomy(data, failure),
        *_verify_fingerprints(data, failure),
    )
    failure_id = data.get("failure_id")
    digest = data.get("bundle_digest")
    return CrashBundleVerification(
        str(path),
        not errors,
        tuple(errors),
        str(failure_id) if failure_id is not None else None,
        str(digest) if digest is not None else None,
    )
