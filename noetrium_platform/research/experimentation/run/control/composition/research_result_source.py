from __future__ import annotations

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchQuerySourceError,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchResultRecord,
    ResearchResultReference,
    ResearchSourceDisposition,
    ResearchSourceSnapshot,
)
from noetrium_platform.evidence.data.query.api.identity import source_cut
from noetrium_platform.research.experimentation.run.control.api import (
    RunControlAction,
    RunControlError,
    RunControlNotFound,
    RunControlPort,
    RunControlReceipt,
    RunControlRequest,
    RunControlTarget,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


def _matches_query(record: ResearchResultRecord, query: ResearchResultQuery) -> bool:
    if query.kinds and record.reference.kind not in query.kinds:
        return False
    dimensions = {item.kind: item for item in record.dimensions}
    return all(dimensions.get(item.kind) == item for item in query.dimensions)


class RunControlResearchResultSource:
    """Read-only ROLE03 projection for one producer-owned run-control authority."""
    source_id = "experimentation.run-control"
    supported_kinds = frozenset({
        ResearchResultKind.RUN,
        ResearchResultKind.EVIDENCE,
    })
    supported_dimensions = frozenset({ResearchDimensionKind.RUN})

    def __init__(
        self,
        control: RunControlPort,
        *,
        run_id: str,
        run_manifest_digest: str,
        scope: ScopeIdentity,
    ) -> None:
        if type(scope) is not ScopeIdentity or scope.kind is not ScopeKind.RUN:
            raise ValueError("run-control result source requires a run scope")
        if scope.scope_id != run_id:
            raise ValueError("run-control result source scope must match run_id")
        self._control = control
        self._target = RunControlTarget(run_id, run_manifest_digest)
        self._scope = scope

    def _inspect(self) -> RunControlReceipt:
        try:
            receipt = self._control.execute(
                RunControlRequest(RunControlAction.INSPECT, self._target)
            )
        except RunControlError as exc:
            disposition = (
                ResearchSourceDisposition.UNAVAILABLE
                if isinstance(exc, RunControlNotFound)
                else ResearchSourceDisposition.INCOMPLETE
            )
            code = (
                "RUN_CONTROL_NOT_FOUND"
                if disposition is ResearchSourceDisposition.UNAVAILABLE
                else "RUN_CONTROL_INTEGRITY_ERROR"
            )
            raise ResearchQuerySourceError(
                self.source_id,
                code,
                str(exc),
                disposition=disposition,
            ) from exc
        if type(receipt) is not RunControlReceipt:
            raise RuntimeError("run-control port returned a non-RunControlReceipt")
        if (
            receipt.run_id != self._target.run_id
            or receipt.run_manifest_digest != self._target.run_manifest_digest
        ):
            raise RuntimeError("run-control receipt identity does not match source binding")
        return receipt

    def _dimensions(self) -> tuple[ResearchDimension, ...]:
        return (ResearchDimension(ResearchDimensionKind.RUN, self._target.run_id),)

    def _record(
        self,
        *,
        kind: ResearchResultKind,
        result_id: str,
        content_sha256: str,
        schema_ref: str,
        lineage: tuple[ResearchResultReference, ...] = (),
    ) -> ResearchResultRecord:
        return ResearchResultRecord(
            reference=ResearchResultReference(kind, result_id, self.source_id),
            scope=self._scope,
            content_sha256=content_sha256,
            schema_ref=schema_ref,
            dimensions=self._dimensions(),
            lineage=lineage,
        )

    def snapshot(self, query: ResearchResultQuery) -> ResearchSourceSnapshot:
        receipt = self._inspect()
        run_reference = ResearchResultReference(
            ResearchResultKind.RUN,
            receipt.run_id,
            self.source_id,
        )
        records = [
            self._record(
                kind=ResearchResultKind.RUN,
                result_id=receipt.run_id,
                content_sha256=receipt.receipt_digest,
                schema_ref="run-control.machine-receipt.v2",
            )
        ]
        evidence = receipt.evidence_bundle_receipt
        if evidence is not None:
            records.append(
                self._record(
                    kind=ResearchResultKind.EVIDENCE,
                    result_id=evidence.bundle_id,
                    content_sha256=evidence.digest,
                    schema_ref="evidence-bundle.receipt.v2",
                    lineage=(run_reference,),
                )
            )
        selected = tuple(
            sorted(
                (record for record in records if _matches_query(record, query)),
                key=lambda row: (row.reference.kind.value, row.reference.result_id),
            )
        )
        return ResearchSourceSnapshot(
            source_id=self.source_id,
            cut=source_cut(self.source_id, query, selected),
            records=selected,
        )


__all__ = ["RunControlResearchResultSource"]
