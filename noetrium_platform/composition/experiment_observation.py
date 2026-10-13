from __future__ import annotations

from noetrium_platform.foundation.governance.api import scope_key
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import study_assignment_text, study_assignment_repetition
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_id

import time

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ExecutionContext,
    canonical_bytes,
)

from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.evidence.observability.capture.api import RecordCapture
from noetrium_platform.evidence.observability.capture.runtime import (
    RegistryBoundRawObservationGateway,
)

class RawLakeStudyTrialObservationSink:
    """Side-plane projection of canonical Trial receipts and Study observations."""

    def __init__(
        self,
        gateway: RegistryBoundRawObservationGateway,
        *,
        system: SystemIdentity = SystemIdentity("experimentation"),
        producer_id: str = "experimentation.study-trial-observation.v1",
    ) -> None:
        self._gateway = gateway
        self._system = system
        self._producer_id = producer_id
        self._gateway.register_producer(producer_id, system)

    @property
    def identity_digest(self) -> str:
        return canonical_digest(
            {
                "sink": self._producer_id,
                "system": self._system.key,
            }
        )

    def publish(self, request, receipt, observation) -> None:
        from noetrium_platform.research.experimentation.lifecycle.study.api import (
            StudyMetricObservation,
            TrialExecutionReceipt,
            TrialExecutionRequest,
        )
        if type(request) is not TrialExecutionRequest:
            raise TypeError("trial observation sink requires TrialExecutionRequest")
        if type(receipt) is not TrialExecutionReceipt:
            raise TypeError("trial observation sink requires TrialExecutionReceipt")
        if type(observation) is not StudyMetricObservation:
            raise TypeError("trial observation sink requires StudyMetricObservation")
        evidence_refs = tuple(
            {
                "reference_id": ref.reference_id,
                "scope": scope_key(ref.scope),
                "artifact_id": ref.artifact_id,
                "generation": ref.generation,
            }
            for ref in receipt.evidence_refs
        )
        payload = {
            "request_digest": request.request_digest,
            "receipt_digest": receipt.receipt_digest,
            "assignment_digest": receipt.assignment_digest,
            "study_id": study_assignment_text(request.assignment, "study_id"),
            "variant_id": study_assignment_text(request.assignment, "variant_id"),
            "repetition": study_assignment_repetition(request.assignment),
            "seed": study_assignment_text(request.assignment, "seed"),
            "measurement_record_digests": tuple(
                row.record_digest for row in receipt.measurements
            ),
            "metrics": observation.metrics,
            "unobserved_metric_names": observation.unobserved_metric_names,
            "evidence_refs": evidence_refs,
            "verifier_receipt_digest": (
                None
                if receipt.verifier_receipt is None
                else receipt.verifier_receipt.receipt_digest
            ),
        }
        context = ExecutionContext(
            run_id=request.run_id,
            trace_id=f"trial:{receipt.receipt_digest}",
            span_id=f"trial:{receipt.assignment_digest[:16]}",
            study_id=study_assignment_text(request.assignment, "study_id"),
            task_id=(
                task_id(request.task_definitions[0])
                if len(request.task_definitions) == 1
                else None
            ),
        )
        now = time.time()
        self._gateway.capture(
            RecordCapture(
                event_id="trial-receipt:" + receipt.receipt_digest,
                family="study.trial.raw",
                context=context,
                system=self._system,
                producer_id=self._producer_id,
                producer_version="1",
                payload=payload,
                raw_payload=canonical_bytes(payload),
                occurred_at=now,
                recorded_at=now,
                status="observed",
                outcome="observed",
                stream_id=request.run_id,
                correlation_id=context.trace_id,
                dimensions={
                    "study_id": study_assignment_text(request.assignment, "study_id"),
                    "variant_id": study_assignment_text(request.assignment, "variant_id"),
                },
            )
        )
