from __future__ import annotations

from noetrium_platform.foundation.governance.architecture.api import (
    ExecutionQualificationPort,
    QualificationEvidence,
    QualificationKind,
    require_production_qualification,
)
from noetrium_platform.research.execution.api import (
    ProgramExecutionPort,
    ProgramExecutionReceipt,
    ProgramExecutionReconciliationResult,
    ProgramExecutionRecoveryPort,
    ProgramExecutionRequest,
)


class QualifiedProgramExecutionBinding:
    """Bind one exact program executor to production qualification authority.

    Program semantics remain in ProgramExecutionRequest.  This composition layer
    only admits an exact request after the existing execution-qualification
    authority attests the selected worker/workload, then binds those immutable
    evidence digests into the returned execution receipt.

    It deliberately does not implement sandbox mechanics.  Process/container/VM/
    WASI/remote-worker implementations stay behind ProgramExecutionPort.
    """

    def __init__(
        self,
        executor: ProgramExecutionPort,
        recovery: ProgramExecutionRecoveryPort,
        qualification: ExecutionQualificationPort,
        *,
        machine_id: str,
        worker_id: str,
    ) -> None:
        if not isinstance(executor, ProgramExecutionPort):
            raise TypeError(
                "qualified program execution requires ProgramExecutionPort"
            )
        if not isinstance(recovery, ProgramExecutionRecoveryPort):
            raise TypeError(
                "qualified program execution requires ProgramExecutionRecoveryPort"
            )
        if recovery.effect_recovery_durability != "crash_durable":
            raise ValueError(
                "qualified program execution requires crash-durable recovery"
            )
        if not isinstance(qualification, ExecutionQualificationPort):
            raise TypeError(
                "qualified program execution requires ExecutionQualificationPort"
            )
        for name, value in (
            ("machine_id", machine_id),
            ("worker_id", worker_id),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"qualified program execution {name} must be canonical text"
                )
        self._executor = executor
        self._recovery = recovery
        self._qualification = qualification
        self._machine_id = machine_id
        self._worker_id = worker_id

    @property
    def effect_recovery_durability(self) -> str:
        return "crash_durable"

    def _qualify(
        self,
        request: ProgramExecutionRequest,
    ) -> tuple[QualificationEvidence, ...]:
        if not isinstance(request, ProgramExecutionRequest):
            raise TypeError(
                "qualified program execution requires ProgramExecutionRequest"
            )
        # The exact request digest already commits the program source identity,
        # capability surface, execution target, isolation requirement, invocation,
        # inputs and resource requirement.  Qualifying that digest therefore
        # qualifies the complete immutable workload rather than an alias.
        return require_production_qualification(
            self._qualification,
            machine_id=self._machine_id,
            worker_id=self._worker_id,
            workload_id=request.request_digest,
        )

    @staticmethod
    def _bind_qualification(
        request: ProgramExecutionRequest,
        receipt: ProgramExecutionReceipt,
        qualification: tuple[QualificationEvidence, ...],
    ) -> ProgramExecutionReceipt:
        if not isinstance(receipt, ProgramExecutionReceipt):
            raise TypeError(
                "qualified program executor must return ProgramExecutionReceipt"
            )
        if receipt.request_digest != request.request_digest:
            raise ValueError(
                "qualified program execution receipt request identity mismatch"
            )
        qualification_digests = tuple(
            row.evidence_digest for row in qualification
        )
        isolation_digests = tuple(
            row.evidence_digest
            for row in qualification
            if row.kind is QualificationKind.ISOLATION
        )
        if not isolation_digests:
            # require_production_qualification currently guarantees this, but keep
            # the local invariant explicit because the execution receipt makes an
            # isolation claim.
            raise ValueError(
                "qualified program execution requires isolation evidence"
            )
        return ProgramExecutionReceipt(
            request_digest=receipt.request_digest,
            status=receipt.status,
            effect_certainty=receipt.effect_certainty,
            result=receipt.result,
            output_artifacts=receipt.output_artifacts,
            effect_receipt_digests=receipt.effect_receipt_digests,
            evidence_digests=tuple(
                sorted(set(receipt.evidence_digests) | set(qualification_digests))
            ),
            isolation_evidence_digests=tuple(
                sorted(
                    set(receipt.isolation_evidence_digests)
                    | set(isolation_digests)
                )
            ),
            failure_code=receipt.failure_code,
        )

    def execute(
        self,
        request: ProgramExecutionRequest,
    ) -> ProgramExecutionReceipt:
        qualification = self._qualify(request)
        receipt = self._executor.execute(request)
        return self._bind_qualification(request, receipt, qualification)

    def reconcile(
        self,
        request: ProgramExecutionRequest,
    ) -> ProgramExecutionReconciliationResult:
        qualification = self._qualify(request)
        result = self._recovery.reconcile(request)
        if not isinstance(result, ProgramExecutionReconciliationResult):
            raise TypeError(
                "qualified program recovery must return "
                "ProgramExecutionReconciliationResult"
            )
        if result.request_digest != request.request_digest:
            raise ValueError(
                "qualified program recovery request identity mismatch"
            )
        receipt = result.receipt
        if receipt is not None:
            receipt = self._bind_qualification(
                request,
                receipt,
                qualification,
            )
        return ProgramExecutionReconciliationResult(
            request_digest=result.request_digest,
            disposition=result.disposition,
            receipt=receipt,
            evidence_digests=tuple(
                sorted(
                    set(result.evidence_digests)
                    | {row.evidence_digest for row in qualification}
                )
            ),
        )


__all__ = ["QualifiedProgramExecutionBinding"]
