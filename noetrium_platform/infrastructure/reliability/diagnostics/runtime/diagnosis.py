from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort, DiagnosticIndexSessionPort
from noetrium_platform.infrastructure.reliability.diagnostics.api.records import freeze_diagnostic_mapping
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG


@dataclass(frozen=True, slots=True)
class FailureDiagnosis:
    failure_id: str
    headline: str
    exact_location: str
    cause: str
    recovery: str
    scientific_risk: str
    related_objects: tuple[Mapping[str, JsonValue], ...]
    recent_state_writers: tuple[Mapping[str, JsonValue], ...]
    next_commands: tuple[str, ...]
    taxonomy: Mapping[str, JsonValue]


class FailureDiagnosisService:
    """Read-only evidence join; causality is never inferred from temporal proximity."""

    def __init__(self, evidence: DiagnosticEvidencePort) -> None:
        self.evidence = evidence

    def why(
        self,
        failure_id: str,
        *,
        window_seconds: float = 30.0,
        writer_limit: int = 12,
        index: DiagnosticIndexSessionPort | None = None,
    ) -> FailureDiagnosis:
        idx = index or self.evidence
        failure_record = idx.locate(failure_id)
        if failure_record is None:
            raise KeyError(f"failure not found: {failure_id}")
        failure = failure_record.payload
        if "failure_domain" not in failure:
            raise KeyError(f"failure not found: {failure_id}")
        context = failure["context"]
        run_id = str(context["run_id"])
        timestamp = float(failure["created_at"])
        related = tuple(record.payload for record in idx.around(
            run_id=run_id, timestamp=timestamp, seconds=window_seconds
        ))
        writers = tuple(record.payload for record in idx.recent_state_writers(
            run_id=run_id, before=timestamp, limit=writer_limit
        ))
        location = "/".join(
            str(value)
            for value in (
                failure.get("component_id"),
                failure.get("stage"),
                context.get("task_id"),
                context.get("decision_cycle_id"),
                failure.get("operation_id"),
            )
            if value
        )
        recovery = failure.get("recommended_recovery") or "manual_diagnosis"
        spec = DEFAULT_FAILURE_CATALOG.get(
            str(failure["failure_domain"]),
            str(failure["failure_code"]),
            str(failure["stage"]),
        )
        taxonomy: dict[str, JsonValue] = {
            "registered": spec is not None,
            "domain": str(failure["failure_domain"]),
            "code": str(failure["failure_code"]),
            "stage": str(failure["stage"]),
            "envelope_spec_digest": failure.get("taxonomy_spec_sha256"),
        }
        if spec is not None:
            current_digest = spec.digest()
            envelope_digest = failure.get("taxonomy_spec_sha256")
            taxonomy.update({
                "default_recovery": spec.default_recovery.value,
                "data_integrity_risk": spec.data_integrity_risk.value,
                "comparability_risk": spec.comparability_risk.value,
                "scientific_validity_risk": spec.scientific_validity_risk.value,
                "description": spec.description,
                "owner": spec.owner,
                "diagnostic_focus": spec.diagnostic_focus,
                "operator_checks": spec.operator_checks,
                "current_spec_digest": current_digest,
                "semantic_drift": (envelope_digest != current_digest) if envelope_digest is not None else None,
            })
        source = self.evidence.source_ref
        return FailureDiagnosis(
            failure_id=failure_id,
            headline=f"{failure['failure_domain']}:{failure['failure_code']}",
            exact_location=location,
            cause=f"{failure.get('cause_type')}: {failure.get('cause_message')}",
            recovery=str(recovery),
            scientific_risk=str(failure.get("scientific_validity_risk", "unknown")),
            related_objects=related,
            recent_state_writers=writers,
            next_commands=(
                f"noetrium-forensics locate {source} {failure_id}",
                f"noetrium-forensics timeline {source} {failure_id}",
                f"noetrium-forensics failure-catalog --domain {failure['failure_domain']} --code {failure['failure_code']}",
                f"noetrium-forensics verify-evidence {source}",
            ),
            taxonomy=freeze_diagnostic_mapping(taxonomy),
        )

    def locate(self, object_id: str) -> dict[str, object]:
        found = self.evidence.locate(object_id)
        if found is None:
            raise KeyError(f"object not found: {object_id}")
        return found.to_payload()

    def timeline(self, object_id: str, *, seconds: float = 30.0) -> tuple[dict[str, object], ...]:
        obj = self.locate(object_id)
        context = obj.get("context") or {}
        run_id = context.get("run_id")
        timestamp = obj.get("created_at", obj.get("timestamp"))
        if not run_id or timestamp is None:
            raise ValueError(f"object has no run/time coordinates: {object_id}")
        return tuple(record.to_payload() for record in self.evidence.around(
            run_id=str(run_id), timestamp=float(timestamp), seconds=seconds
        ))

    def last_writer(self, run_id: str, state_name: str) -> dict[str, object]:
        found = self.evidence.last_writer(run_id, state_name)
        if found is None:
            raise KeyError(f"no writer for state={state_name!r} run={run_id!r}")
        return found.to_payload()
