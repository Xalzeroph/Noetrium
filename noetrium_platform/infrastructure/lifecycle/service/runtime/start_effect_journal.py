from __future__ import annotations

from dataclasses import replace
import time

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    canonical_digest,
)
from noetrium_platform.foundation.api import (
    EffectIntentJournal,
    EffectIntentPhase,
    completion_field,
    effect_completion,
    effect_intent,
    effect_result_snapshot,
    intent_field,
    prepared_effect_handle,
    prepared_handle_field,
    record_field,
    result_snapshot_field,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
)

from .prepared_start import ServiceStartRecoveryHandle
from .start_intent_codec import ServiceStartIntentCodec
from .start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase


_SERVICE_START_PROJECTION_SCHEMA = "service.start.projection.v3"


class ServiceStartEffectConflict(RuntimeError):
    pass


def service_start_intent_id(contract: ServiceLaunchContract, attempt: int) -> str:
    if type(attempt) is not int or attempt <= 0:
        raise ValueError("service start attempt must be positive")
    return "service-start:" + canonical_digest(
        {
            "service_id": contract.service_id,
            "contract_digest": contract.digest(),
            "attempt": attempt,
        }
    )


def _run_id(contract: ServiceLaunchContract) -> str:
    return "service:" + contract.service_id


def _process_receipt(intent: ServiceStartIntent) -> EffectReceipt:
    process = intent.process
    if process is None:
        raise ServiceStartEffectConflict("service start process receipt requires process")
    return EffectReceipt(
        effect_id=intent.intent_id,
        request_digest=intent.contract_digest,
        effect_class=EffectClass.RECONCILABLE,
        certainty=EffectCertainty.EFFECT_CONFIRMED,
        provider_instance_id=intent.contract.runtime_identity_digest,
        provider_receipt=canonical_digest(
            {
                "pid": process.pid,
                "start_identity": process.start_identity,
                "process_group_id": process.process_group_id,
                "control_pid": process.control_pid,
                "anchor_pid": process.anchor_pid,
                "anchor_start_identity": process.anchor_start_identity,
                "anchor_control_pid": process.anchor_control_pid,
            }
        ),
    )


class ServiceStartEffectJournal:
    """Service-start projection over the universal causal Effect journal.

    No service-specific WAL, active pointer or authoritative JSON document exists.
    The durable truth is effect.intent/effect.record/system.event.  ServiceStartIntent
    remains only a typed projection consumed by the exact-service state machine.
    """

    def __init__(
        self,
        journal: EffectIntentJournal,
        *,
        codec: ServiceStartIntentCodec | None = None,
    ) -> None:
        if not isinstance(journal, EffectIntentJournal):
            raise TypeError("service start requires EffectIntentJournal")
        self.journal = journal
        self.codec = codec or ServiceStartIntentCodec()

    def close(self) -> None:
        self.journal.close()

    def _projection_snapshot(self, value: ServiceStartIntent):
        return effect_result_snapshot(
            schema=_SERVICE_START_PROJECTION_SCHEMA,
            opaque_payload=self.codec.encode(value),
        )

    def _projection_from_record(self, record) -> ServiceStartIntent:
        effect_intent_unit = record_field(record, "intent")
        wrapper = intent_field(effect_intent_unit, "recovery_handle")
        if wrapper is None:
            raise ServiceStartEffectConflict(
                "service start effect intent lacks frozen projection seed"
            )
        seed = self.codec.decode(prepared_handle_field(wrapper, "opaque_payload"))
        if prepared_handle_field(wrapper, "request_id") != seed.intent_id:
            raise ServiceStartEffectConflict("service start effect request identity drifted")
        if prepared_handle_field(wrapper, "request_digest") != seed.contract_digest:
            raise ServiceStartEffectConflict("service start effect contract digest drifted")

        phase = record_field(record, "phase")
        snapshot = record_field(record, "result_snapshot")
        current = seed
        if snapshot is not None:
            if result_snapshot_field(snapshot, "schema") != _SERVICE_START_PROJECTION_SCHEMA:
                raise ServiceStartEffectConflict("service start result snapshot schema drifted")
            current = self.codec.decode(
                result_snapshot_field(snapshot, "opaque_payload")
            )
        if current.intent_id != seed.intent_id or current.contract != seed.contract:
            raise ServiceStartEffectConflict("service start projection identity drifted")

        if phase is EffectIntentPhase.PREPARED:
            if current.phase is not ServiceStartIntentPhase.PREPARED:
                raise ServiceStartEffectConflict("prepared effect has non-prepared projection")
            return current
        if phase is EffectIntentPhase.RESULT_RECORDED:
            if current.phase is not ServiceStartIntentPhase.PROCESS_CONFIRMED:
                raise ServiceStartEffectConflict(
                    "result-recorded effect lacks process-confirmed projection"
                )
            return current
        if phase is EffectIntentPhase.RECONCILED:
            if current.phase is not ServiceStartIntentPhase.STATE_COMMITTED:
                raise ServiceStartEffectConflict(
                    "reconciled effect lacks state-committed projection"
                )
            return current
        if phase is EffectIntentPhase.NOT_APPLIED:
            if current.process is not None:
                raise ServiceStartEffectConflict(
                    "NOT_APPLIED service start cannot retain physical process"
                )
            return replace(current, phase=ServiceStartIntentPhase.ABORTED)
        if phase is EffectIntentPhase.CONSUMED:
            completion = record_field(record, "consumption")
            if completion is None:
                raise ServiceStartEffectConflict("consumed service start lacks completion")
            operation = str(completion_field(completion, "completion_operation_id"))
            if operation == "service.start.complete":
                target = ServiceStartIntentPhase.COMPLETE
            elif operation == "service.start.abort-after-cleanup":
                target = ServiceStartIntentPhase.ABORTED
            else:
                raise ServiceStartEffectConflict(
                    "unknown service start completion operation: " + operation
                )
            return replace(current, phase=target)
        raise ServiceStartEffectConflict(
            "indeterminate service start requires explicit physical reconciliation"
        )

    def get(self, intent_id: str) -> ServiceStartIntent:
        record = self.journal.load(intent_id)
        if record is None:
            raise KeyError(intent_id)
        return self._projection_from_record(record)

    def prepare(
        self,
        contract: ServiceLaunchContract,
        *,
        attempt: int,
        recovery_handle: ServiceStartRecoveryHandle | None,
    ) -> ServiceStartIntent:
        intent_id = service_start_intent_id(contract, attempt)
        now = time.time()
        candidate = ServiceStartIntent(
            intent_id,
            contract,
            attempt,
            ServiceStartIntentPhase.PREPARED,
            recovery_handle,
            None,
            now,
            now,
        )
        wrapper = prepared_effect_handle(
            request_id=intent_id,
            request_digest=contract.digest(),
            provider_schema=_SERVICE_START_PROJECTION_SCHEMA,
            opaque_payload=self.codec.encode(candidate),
            provider_instance_id=contract.runtime_identity_digest,
        )
        declared = effect_intent(
            intent_id=intent_id,
            request_id=intent_id,
            operation_id="service.start",
            request_digest=contract.digest(),
            provider_component_digest=contract.runtime_identity_digest,
            run_id=_run_id(contract),
            trace_id="service-start:" + contract.digest(),
            study_id=None,
            lifetime_id=contract.digest(),
            task_id=None,
            decision_cycle_id=None,
            source_generation=contract.generation,
            recovery_handle=wrapper,
        )
        result = self.journal.prepare(declared)
        current = self._projection_from_record(result.record)
        if (
            current.contract != candidate.contract
            or current.attempt != candidate.attempt
            or current.recovery_handle != candidate.recovery_handle
        ):
            raise ServiceStartEffectConflict(
                "service start effect identity already bound differently"
            )
        return current

    def record_process(
        self,
        intent: ServiceStartIntent,
        process: ServiceProcessIdentity,
    ) -> ServiceStartIntent:
        current = self.get(intent.intent_id)
        if current.process is not None and current.process != process:
            raise ServiceStartEffectConflict("service start process identity changed")
        if current.phase is ServiceStartIntentPhase.ABORTED:
            raise ServiceStartEffectConflict("aborted service start cannot acquire process")
        if current.phase in {
            ServiceStartIntentPhase.STATE_COMMITTED,
            ServiceStartIntentPhase.COMPLETE,
        }:
            if current.process != process:
                raise ServiceStartEffectConflict(
                    "committed service start disagrees on process"
                )
            return current
        updated = replace(
            current,
            phase=ServiceStartIntentPhase.PROCESS_CONFIRMED,
            process=process,
            updated_at=time.time(),
        )
        record = self.journal.record_result(
            current.intent_id,
            request_digest=current.contract_digest,
            effect=_process_receipt(updated),
            result_snapshot=self._projection_snapshot(updated),
        )
        return self._projection_from_record(record)

    def state_committed(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        current = self.get(intent.intent_id)
        if current.process is None:
            raise ServiceStartEffectConflict("cannot commit service start without process")
        if current.phase is ServiceStartIntentPhase.ABORTED:
            raise ServiceStartEffectConflict("aborted service start cannot commit state")
        if current.phase is ServiceStartIntentPhase.COMPLETE:
            return current
        updated = replace(
            current,
            phase=ServiceStartIntentPhase.STATE_COMMITTED,
            updated_at=time.time(),
        )
        record = self.journal.record_reconciled(
            current.intent_id,
            request_digest=current.contract_digest,
            effect=_process_receipt(updated),
            result_snapshot=self._projection_snapshot(updated),
        )
        return self._projection_from_record(record)

    def complete(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        current = self.get(intent.intent_id)
        if current.phase is ServiceStartIntentPhase.ABORTED:
            raise ServiceStartEffectConflict("aborted service start cannot complete")
        if current.process is None:
            raise ServiceStartEffectConflict("cannot complete service start without process")
        if current.phase is ServiceStartIntentPhase.COMPLETE:
            return current
        completion = effect_completion(
            completion_key=current.intent_id + ":complete",
            completion_operation_id="service.start.complete",
            consumer_component_digest=canonical_digest("service-supervisor"),
            consumer_generation=current.contract.generation,
        )
        record = self.journal.record_consumed(
            current.intent_id,
            request_digest=current.contract_digest,
            consumption=completion,
        )
        return self._projection_from_record(record)

    def abort(self, intent: ServiceStartIntent) -> ServiceStartIntent:
        """Terminalize only after caller has proven physical cleanup."""

        current = self.get(intent.intent_id)
        if current.phase is ServiceStartIntentPhase.COMPLETE:
            raise ServiceStartEffectConflict("completed service start cannot be aborted")
        if current.phase is ServiceStartIntentPhase.ABORTED:
            return current
        record = self.journal.load(current.intent_id)
        if record is None:
            raise KeyError(current.intent_id)
        effect = record_field(record, "effect")
        if effect is None:
            proof = EffectReceipt(
                effect_id=current.intent_id,
                request_digest=current.contract_digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.NO_EFFECT,
                provider_instance_id=current.contract.runtime_identity_digest,
                provider_receipt="service-start-aborted-before-process",
            )
            updated_record = self.journal.record_not_applied(
                current.intent_id,
                request_digest=current.contract_digest,
                effect=proof,
            )
        else:
            completion = effect_completion(
                completion_key=current.intent_id + ":abort",
                completion_operation_id="service.start.abort-after-cleanup",
                consumer_component_digest=canonical_digest("service-supervisor"),
                consumer_generation=current.contract.generation,
            )
            updated_record = self.journal.record_consumed(
                current.intent_id,
                request_digest=current.contract_digest,
                consumption=completion,
            )
        return self._projection_from_record(updated_record)

    def records_for_service(
        self,
        service_id: str,
    ) -> tuple[ServiceStartIntent, ...]:
        if type(service_id) is not str or not service_id.strip():
            raise ValueError("service start service_id must be non-empty")
        return tuple(
            self._projection_from_record(record)
            for record in self.journal.records_for_run(
                "service:" + service_id.strip()
            )
        )

    def records_for_contract(
        self,
        contract: ServiceLaunchContract,
    ) -> tuple[ServiceStartIntent, ...]:
        """Project every start Effect for one exact frozen launch contract."""
        if not isinstance(contract, ServiceLaunchContract):
            raise TypeError("service start contract history requires ServiceLaunchContract")
        digest = contract.digest()
        rows = tuple(
            intent
            for intent in self.records_for_service(contract.service_id)
            if intent.contract_digest == digest and intent.contract == contract
        )
        return tuple(
            sorted(
                rows,
                key=lambda row: (row.attempt, row.updated_at, row.intent_id),
            )
        )

    def unresolved_scope(
        self,
        service_id: str,
        contract_digest: str,
    ) -> tuple[ServiceStartIntent, ...]:
        if type(service_id) is not str or not service_id.strip():
            raise ValueError("service start scope service_id must be non-empty")
        if (
            type(contract_digest) is not str
            or len(contract_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in contract_digest)
        ):
            raise ValueError(
                "service start scope contract_digest must be lowercase SHA-256"
            )
        records = tuple(
            record
            for record in self.journal.unresolved_for_scope(
                run_id="service:" + service_id.strip(),
                lifetime_id=contract_digest,
            )
            if intent_field(record_field(record, "intent"), "request_digest")
            == contract_digest
        )
        return tuple(self._projection_from_record(record) for record in records)

    def unresolved(self, contract: ServiceLaunchContract) -> ServiceStartIntent | None:
        values = self.unresolved_scope(contract.service_id, contract.digest())
        if len(values) > 1:
            raise ServiceStartEffectConflict(
                "multiple unresolved starts for one frozen service contract"
            )
        return None if not values else values[0]




__all__ = [
    "ServiceStartEffectConflict",
    "ServiceStartEffectJournal",
    "service_start_intent_id",
]
