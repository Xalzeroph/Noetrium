from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG, fingerprint_failure
from noetrium_platform.infrastructure.reliability.forensics.api.crash_bundle_contracts import (
    CRASH_BUNDLE_SCHEMA_VERSION,
    CrashBundleManifest,
    CrashBundleVerification,
)
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicStorePort


class CrashBundleBuilder:
    """Immutable offline forensic manifest; large raw artifacts remain referenced, not copied."""

    SCHEMA_VERSION = CRASH_BUNDLE_SCHEMA_VERSION

    def __init__(self, store: ForensicStorePort) -> None:
        self.store = store

    @staticmethod
    def _taxonomy(failure: dict[str, object]) -> dict[str, object]:
        domain = str(failure["failure_domain"])
        code = str(failure["failure_code"])
        stage = str(failure["stage"])
        envelope_digest = failure.get("taxonomy_spec_sha256")
        spec = DEFAULT_FAILURE_CATALOG.get(domain, code, stage)
        result: dict[str, object] = {
            "registered": spec is not None,
            "domain": domain,
            "code": code,
            "stage": stage,
            "envelope_spec_digest": envelope_digest,
        }
        if spec is not None:
            current = spec.digest()
            result.update({
                "current_spec_digest": current,
                "semantic_drift": (envelope_digest != current) if envelope_digest is not None else None,
                "spec": {
                    "default_recovery": spec.default_recovery.value,
                    "data_integrity_risk": spec.data_integrity_risk.value,
                    "comparability_risk": spec.comparability_risk.value,
                    "scientific_validity_risk": spec.scientific_validity_risk.value,
                    "description": spec.description,
                    "owner": spec.owner,
                    "diagnostic_focus": spec.diagnostic_focus,
                    "operator_checks": spec.operator_checks,
                },
            })
        return result

    @staticmethod
    def _fingerprints(failure: dict[str, object]) -> dict[str, object]:
        fingerprint = fingerprint_failure(failure)
        return {
            "exact": fingerprint.fingerprint,
            "family": fingerprint.family_fingerprint,
            "exact_signature": fingerprint.signature,
            "family_signature": fingerprint.family_signature,
        }

    def build(self, failure_id: str, *, writer_limit: int = 16, window_seconds: float = 60.0) -> CrashBundleManifest:
        failure_record = self.store.index.locate(failure_id)
        if failure_record is None:
            raise KeyError(f"failure not found: {failure_id}")
        failure = failure_record.to_payload()
        if "failure_domain" not in failure:
            raise KeyError(f"failure not found: {failure_id}")
        context = failure["context"]
        run_id = str(context["run_id"])
        timestamp = float(failure["created_at"])
        timeline = tuple(record.to_payload() for record in self.store.index.around(
            run_id=run_id, timestamp=timestamp, seconds=window_seconds
        ))
        writers = tuple(record.to_payload() for record in self.store.index.recent_state_writers(
            run_id=run_id, before=timestamp, limit=writer_limit
        ))
        verified = self.store.verify_all()
        tails = {name: {"rows": rows, "tail_hash": tail} for name, (rows, tail) in verified.items()}
        artifacts = tuple(dict.fromkeys(tuple(failure.get("input_artifacts", ())) + tuple(failure.get("output_artifacts", ()))))
        taxonomy = self._taxonomy(failure)
        fingerprints = self._fingerprints(failure)
        base = {
            "schema_version": self.SCHEMA_VERSION,
            "failure_id": failure_id,
            "failure": failure,
            "taxonomy": taxonomy,
            "fingerprints": fingerprints,
            "timeline": timeline,
            "recent_state_writers": writers,
            "authoritative_chain_tails": tails,
            "artifact_refs": artifacts,
        }
        raw = json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        return CrashBundleManifest(
            self.SCHEMA_VERSION,
            failure_id,
            failure,
            taxonomy,
            fingerprints,
            timeline,
            writers,
            tails,
            artifacts,
            digest,
        )

    def publish(self, failure_id: str, path: Path) -> CrashBundleManifest:
        manifest = self.build(failure_id)
        payload = json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        atomic_replace_bytes(path, payload)
        return manifest


from noetrium_platform.infrastructure.reliability.forensics.runtime.crash_bundle_verify import verify_crash_bundle

__all__ = ["CrashBundleBuilder", "CrashBundleManifest", "CrashBundleVerification", "verify_crash_bundle"]
