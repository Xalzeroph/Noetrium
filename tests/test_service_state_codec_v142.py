from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.service.runtime.state_storage import FileServiceStateStore
from noetrium_platform.foundation.kernel.kernel.durability import ChecksummedDocumentFailureCode
from noetrium_platform.infrastructure.lifecycle.service.runtime import (
    ServiceExitClass,
    ServiceReadyEvidence,
    ServiceStateIntegrityError,
    ServiceSupervisorState,
)


class ServiceStateCodecV142Tests(unittest.TestCase):
    def _state(self) -> ServiceSupervisorState:
        return replace(
            ServiceSupervisorState.initial("model.planner", "a" * 64),
            attempt=3,
            process=ServiceProcessIdentity(42, "pid:42:start:7", 42),
            last_exit_class=ServiceExitClass.SOFTWARE,
        )

    def test_new_document_is_versioned_checksummed_and_round_trips(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "service.json"
            store = FileServiceStateStore(path)
            state = self._state()
            store.write(state)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], "service-supervisor-state.v3")
            self.assertEqual(len(document["payload_sha256"]), 64)
            self.assertEqual(store.read(), state)

    def test_payload_tampering_is_detected_before_state_construction(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "service.json"
            store = FileServiceStateStore(path)
            store.write(self._state())
            document = json.loads(path.read_text(encoding="utf-8"))
            document["payload"]["attempt"] = 999
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ServiceStateIntegrityError) as caught:
                store.read()
            self.assertIs(caught.exception.document_failure_code, ChecksummedDocumentFailureCode.CHECKSUM_MISMATCH)

    def test_unknown_future_schema_fails_closed(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "service.json"
            path.write_text(json.dumps({"schema": "service-supervisor-state.v999"}), encoding="utf-8")
            with self.assertRaises(ServiceStateIntegrityError) as caught:
                FileServiceStateStore(path).read()
            self.assertIs(caught.exception.document_failure_code, ChecksummedDocumentFailureCode.UNSUPPORTED_SCHEMA)

    def test_unenveloped_state_is_rejected(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "service.json"
            state = self._state()
            payload = asdict(state)
            payload["phase"] = state.phase.value
            payload["last_exit_class"] = int(state.last_exit_class)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ServiceStateIntegrityError) as caught:
                FileServiceStateStore(path).read()
            self.assertIs(caught.exception.document_failure_code, ChecksummedDocumentFailureCode.SCHEMA_MISSING)


class ServiceReadyAtV32Tests(unittest.TestCase):
    def _contract(self):
        from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
        return ServiceLaunchContract(
            "svc", "g1", "/opt/rp/python", ("/opt/rp/python", "-m", "svc"), "/srv/rp",
            "a" * 64, "b" * 64, "c" * 64, 10.0, 10.0, 1.0,
        )

    def test_ready_at_round_trips_as_independent_durable_authority(self):
        from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
        state = replace(
            ServiceSupervisorState.initial("svc", "d" * 64),
            phase=ServicePhase.RUNNING, ready_evidence_ref="ready:1", ready_at=1234.5,
        )
        with TemporaryDirectory() as td:
            store = FileServiceStateStore(Path(td) / "service.json")
            store.write(state)
            self.assertEqual(store.read().ready_at, 1234.5)

    def test_ready_evidence_without_ready_at_fails_durable_encoding(self):
        state = replace(ServiceSupervisorState.initial("svc", "d" * 64), ready_evidence_ref="ready:1")
        with TemporaryDirectory() as td:
            with self.assertRaises(ServiceStateIntegrityError):
                FileServiceStateStore(Path(td) / "service.json").write(state)


class ServiceReadyProjectionV32Tests(unittest.TestCase):
    def test_producer_ready_at_is_persisted_preserved_and_publicly_projected(self):
        from unittest.mock import patch
        from noetrium_platform.infrastructure.lifecycle.service.api import (
            ServiceLaunchContract, ServiceProcessIdentity, ServiceReconcileObservation,
        )
        from noetrium_platform.infrastructure.lifecycle.service.runtime import ServicePhase
        from noetrium_platform.infrastructure.lifecycle.service.runtime.runtime_endpoint import ExactServiceRuntimeEndpoint
        from noetrium_platform.infrastructure.lifecycle.service.runtime.start_flow_common import ServiceReadinessCommitter
        from noetrium_platform.infrastructure.lifecycle.service.runtime.state_transition import ServiceStateTransitionWriter

        contract = ServiceLaunchContract(
            "svc", "g1", "/opt/rp/python", ("/opt/rp/python", "-m", "svc"), "/srv/rp",
            "a" * 64, "b" * 64, "c" * 64, 10.0, 10.0, 1.0,
        )
        process = ServiceProcessIdentity(42, "start:42")

        class Store:
            def __init__(self): self.state = None
            def write(self, state): self.state = state
        proof = ServiceReadyEvidence(
            contract.digest(), process, "ready:producer", "stdout:producer", "stderr:producer", 1777.25
        )
        class Adapter:
            def wait_ready(self, observed_process, observed_contract):
                self.assertions = (observed_process, observed_contract)
                return proof

        store = Store(); adapter = Adapter()
        transitions = ServiceStateTransitionWriter(store)
        committer = ServiceReadinessCommitter(adapter, transitions)
        initial = ServiceSupervisorState.initial(contract.service_id, contract.digest())
        with patch("noetrium_platform.infrastructure.lifecycle.service.runtime.state_transition.time.time", return_value=2000.0):
            state, _refs = committer.commit(contract, initial, process)
        self.assertEqual(state.ready_at, 1777.25)
        self.assertEqual(state.last_heartbeat_at, 1777.25)
        second_store = Store()
        second = ServiceReadinessCommitter(Adapter(), ServiceStateTransitionWriter(second_store))
        with patch("noetrium_platform.infrastructure.lifecycle.service.runtime.state_transition.time.time", return_value=3000.0):
            second_state, _ = second.commit(contract, initial, process)
        self.assertEqual((state.ready_at, second_state.ready_at), (1777.25, 1777.25))
        self.assertEqual((state.updated_at, second_state.updated_at), (2000.0, 3000.0))
        heartbeat = transitions.persist(state, ServicePhase.RUNNING, last_heartbeat_at=1888.0)
        self.assertEqual(heartbeat.ready_at, 1777.25)

        class Supervisor:
            def observe_state(self, observed_contract): return heartbeat
            def reconcile_exact(self, observed_contract):
                return ServiceReconcileObservation(True, process, ("reconcile:producer",))
        observation = ExactServiceRuntimeEndpoint(Supervisor()).verify_ready_exact(contract)
        self.assertEqual(observation.ready_at, 1777.25)
        self.assertEqual(observation.ready_evidence_ref, "ready:producer")


class ServiceReadinessReceiptAuthorityV32Tests(unittest.TestCase):
    def _contract(self):
        from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
        return ServiceLaunchContract(
            "svc", "g1", "/opt/rp/python", ("/opt/rp/python", "-m", "svc"), "/srv/rp",
            "a" * 64, "b" * 64, "c" * 64, 10.0, 10.0, 1.0,
        )

    def test_local_adapter_freezes_timestamped_identity_bound_receipt_at_probe_success(self):
        from unittest.mock import patch
        from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
        from noetrium_platform.infrastructure.lifecycle.service.runtime import LocalServiceProcessAdapter
        from noetrium_platform.infrastructure.lifecycle.service.runtime.capture_paths import DirectoryCapturePathProvider
        contract = self._contract(); process = ServiceProcessIdentity(42, "start:42")
        backend = object()
        class Probe:
            def wait_ready(self, observed_process, observed_contract, observed_backend):
                self.observed = (observed_process, observed_contract, observed_backend)
                return "ready:probe"
        probe = Probe()
        with TemporaryDirectory() as td, patch(
            "noetrium_platform.infrastructure.lifecycle.service.runtime.process_adapter.time.time", return_value=1555.5
        ):
            adapter = LocalServiceProcessAdapter(object(), DirectoryCapturePathProvider(Path(td)), backend, probe)
            receipt = adapter.wait_ready(process, contract)
        self.assertEqual(receipt.contract_digest, contract.digest())
        self.assertEqual(receipt.process, process)
        self.assertEqual(receipt.readiness_ref, "ready:probe")
        self.assertEqual(receipt.ready_at, 1555.5)
        self.assertEqual(probe.observed, (process, contract, backend))

    def test_readiness_receipt_rejects_noncanonical_identity_and_nonfinite_time(self):
        from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
        process = ServiceProcessIdentity(42, "start:42")
        with self.assertRaises(ValueError):
            ServiceReadyEvidence("A" * 64, process, "ready", "stdout", "stderr", 1.0)
        with self.assertRaises(ValueError):
            ServiceReadyEvidence("a" * 64, process, "ready", "stdout", "stderr", float("nan"))
        with self.assertRaises(ValueError):
            ServiceReadyEvidence("a" * 64, process, "ready", "stdout", "stderr", True)

    def test_committer_rejects_receipt_rebound_to_different_process(self):
        from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
        from noetrium_platform.infrastructure.lifecycle.service.runtime import ServiceReadinessProofMismatch
        from noetrium_platform.infrastructure.lifecycle.service.runtime.start_flow_common import ServiceReadinessCommitter
        from noetrium_platform.infrastructure.lifecycle.service.runtime.state_transition import ServiceStateTransitionWriter
        contract = self._contract(); process = ServiceProcessIdentity(42, "start:42")
        forged = ServiceReadyEvidence(contract.digest(), ServiceProcessIdentity(99, "start:99"), "ready", "stdout", "stderr", 5.0)
        class Store:
            def write(self, state): self.state = state
        class Adapter:
            def wait_ready(self, observed_process, observed_contract): return forged
        committer = ServiceReadinessCommitter(Adapter(), ServiceStateTransitionWriter(Store()))
        with self.assertRaises(ServiceReadinessProofMismatch):
            committer.commit(contract, ServiceSupervisorState.initial(contract.service_id, contract.digest()), process)


if __name__ == "__main__":
    unittest.main()
