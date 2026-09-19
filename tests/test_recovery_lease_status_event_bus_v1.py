from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.evidence.observability.status.api import HealthState
from noetrium_platform.evidence.observability.status.runtime import (
    InMemoryStatusEventBus,
    JsonStateStatusProbe,
    RecoveryLeaseStatusProbe,
)
from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLease
from noetrium_platform.infrastructure.reliability.recovery.composition import compose_recovery_lease_status_probe


class Source:
    def __init__(self, lease: RecoveryLease | None) -> None:
        self.lease = lease

    def read(self) -> RecoveryLease | None:
        return self.lease

    def evidence_refs(self) -> tuple[str, ...]:
        return ("lease-state:stable",)


def test_recovery_status_is_published_then_consumed_through_event_bus() -> None:
    probe = compose_recovery_lease_status_probe(Source(None), clock=lambda: 100.0)
    snapshot = probe.snapshot()
    assert snapshot.state is HealthState.READY
    assert snapshot.summary == "no active recovery owner"


def test_active_recovery_lease_event_preserves_observation_evidence() -> None:
    source = Source(RecoveryLease("owner-a", "manifest-a", 10.0, 160.0))
    snapshot = compose_recovery_lease_status_probe(source, clock=lambda: 100.0).snapshot()
    assert snapshot.state is HealthState.READY
    assert snapshot.summary == "owner=owner-a; expires_in=60.0s"
    assert snapshot.evidence == ("lease-state:stable",)


def test_expired_recovery_lease_event_is_failed_with_recovery_action() -> None:
    source = Source(RecoveryLease("owner-a", "manifest-a", 10.0, 99.0))
    snapshot = compose_recovery_lease_status_probe(source, clock=lambda: 100.0).snapshot()
    assert snapshot.state is HealthState.FAILED
    assert snapshot.reason_codes == ("recovery_lease_expired",)
    assert "inspect stale recovery owner" in snapshot.next_commands[0]


def test_observation_probe_reports_missing_event_without_reliability_dependency() -> None:
    snapshot = RecoveryLeaseStatusProbe(InMemoryStatusEventBus()).snapshot()
    assert snapshot.state is HealthState.UNKNOWN
    assert snapshot.reason_codes == ("status_event_missing",)


def _write_json_state(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def test_json_status_missing_phase_is_unknown_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_json_state(path, {"detail": "no phase authority"})
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.UNKNOWN
    assert snapshot.reason_codes == ("state_phase_missing",)


def test_json_status_unrecognized_phase_is_unknown_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_json_state(path, {"phase": "starting"})
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.UNKNOWN
    assert snapshot.reason_codes == ("state_phase_unrecognized",)


def test_json_status_non_string_phase_is_unknown_not_coerced(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_json_state(path, {"phase": 123})
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.UNKNOWN
    assert snapshot.reason_codes == ("state_phase_invalid_type",)



def test_json_status_duplicate_phase_is_degraded_evidence_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"phase":"failed","phase":"ready"}', encoding="utf-8")
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.DEGRADED_EVIDENCE
    assert snapshot.reason_codes == ("state_record_invalid",)


def test_json_status_non_finite_evidence_is_degraded(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"phase":"ready","detail":NaN}', encoding="utf-8")
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.DEGRADED_EVIDENCE
    assert snapshot.reason_codes == ("state_record_invalid",)

def test_json_status_explicit_operational_and_failure_phases_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_json_state(path, {"phase": "running"})
    ready = JsonStateStatusProbe("model", path).snapshot()
    assert ready.state is HealthState.READY

    _write_json_state(path, {"phase": "failed", "last_failure_id": "failure:1"})
    failed = JsonStateStatusProbe("model", path).snapshot()
    assert failed.state is HealthState.FAILED
    assert failed.failure_id == "failure:1"


def test_json_status_failure_id_is_not_silently_coerced(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _write_json_state(path, {"phase": "failed", "last_failure_id": 123})
    snapshot = JsonStateStatusProbe("model", path).snapshot()
    assert snapshot.state is HealthState.FAILED
    assert snapshot.failure_id is None
    assert "state_failure_id_invalid" in snapshot.reason_codes
