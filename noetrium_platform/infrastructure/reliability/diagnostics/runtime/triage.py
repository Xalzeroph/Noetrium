from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.diagnostics.api import DiagnosticEvidencePort
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG


@dataclass(frozen=True, slots=True)
class TriageStep:
    order: int
    check: str
    reason: str
    command: str | None
    required_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeterministicTriagePlan:
    failure_id: str
    owner: str
    recovery_action: str
    scientific_risk: str
    diagnostic_focus: tuple[str, ...]
    steps: tuple[TriageStep, ...]


class TriagePlanService:
    """Build deterministic evidence-first debugging plans; never executes recovery."""

    def __init__(self, evidence: DiagnosticEvidencePort) -> None:
        self.evidence = evidence

    def build(self, failure_id: str) -> DeterministicTriagePlan:
        failure_record = self.evidence.locate(failure_id)
        if failure_record is None:
            raise KeyError(f"failure not found: {failure_id}")
        failure = failure_record.payload
        if "failure_domain" not in failure:
            raise KeyError(f"failure not found: {failure_id}")
        domain = str(failure["failure_domain"])
        code = str(failure["failure_code"])
        stage = str(failure["stage"])
        spec = DEFAULT_FAILURE_CATALOG.get(domain, code, stage)
        owner = spec.owner if spec is not None else str(failure.get("component_id") or "unknown")
        focus = spec.diagnostic_focus if spec is not None else ()
        recovery = (
            spec.default_recovery.value
            if spec is not None
            else str(failure.get("recommended_recovery") or "manual_diagnosis")
        )
        source = self.evidence.source_ref
        steps: list[TriageStep] = [
            TriageStep(1, "taxonomy", "Confirm stable error semantics and taxonomy version.", f"noetrium-forensics failure-catalog --domain {domain} --code {code}"),
            TriageStep(2, "evidence_integrity", "Verify authoritative evidence before trusting projections.", f"noetrium-forensics verify-evidence {source}"),
            TriageStep(3, "exact_location", "Locate the exact failure object and execution identity.", f"noetrium-forensics locate {source} {failure_id}"),
            TriageStep(4, "joined_debug_snapshot", "Join timeline, causal refs, state writers and nearby telemetry.", f"noetrium-forensics debug-snapshot {source} {failure_id}"),
        ]
        existing = {step.check for step in steps}
        next_order = 5
        for check in spec.operator_checks if spec is not None else ():
            if check in existing:
                continue
            command: str | None
            missing: tuple[str, ...]
            if check in {"timeline", "index-status"}:
                command = (
                    f"noetrium-forensics timeline {source} {failure_id}"
                    if check == "timeline"
                    else f"noetrium-forensics index-status {source}"
                )
                missing = ()
            elif check == "debug-snapshot":
                command = f"noetrium-forensics debug-snapshot {source} {failure_id}"
                missing = ()
            elif check == "verify-evidence":
                command = f"noetrium-forensics verify-evidence {source}"
                missing = ()
            elif check == "failure-catalog":
                command = f"noetrium-forensics failure-catalog --domain {domain} --code {code}"
                missing = ()
            elif check == "last-writer":
                command = None
                missing = ("state_name",)
            elif check == "telemetry-query":
                command = None
                missing = ("telemetry_db",)
            elif check == "runtime-status":
                command = None
                missing = ("runtime_status_layout",)
            elif check == "crash-bundle-verify":
                command = None
                missing = ("crash_bundle_path",)
            elif check == "release-verify":
                command = None
                missing = ("source_root", "release_manifest")
            else:
                command = None
                missing = ("operator_specific_input",)
            steps.append(TriageStep(next_order, check, f"Catalog-directed check owned by {owner}.", command, missing))
            existing.add(check)
            next_order += 1
        return DeterministicTriagePlan(
            failure_id,
            owner,
            recovery,
            str(failure.get("scientific_validity_risk") or "unknown"),
            focus,
            tuple(steps),
        )
