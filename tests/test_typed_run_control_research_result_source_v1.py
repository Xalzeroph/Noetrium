from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.evidence.data.query.api import (
    ResearchDimension,
    ResearchDimensionKind,
    ResearchResultKind,
    ResearchResultQuery,
    ResearchSourceDisposition,
)
from noetrium_platform.foundation.kernel.kernel import MachineCut
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
)
from noetrium_platform.research.experimentation.run.control.api import (
    RunControlAction,
    RunControlNotFound,
    RunControlPhase,
    RunControlReceipt,
    RunControlTarget,
    RunEvidenceValidity,
    RunExecutionOutcome,
    RunOutcomeProjection,
    RunScientificValidity,
    RunTaskOutcome,
)
from noetrium_platform.research.experimentation.run.control.composition import (
    RunControlResearchResultSource,
)
from noetrium_platform.research.experimentation.run.manifest.api import (
    EvidenceBundleReceipt,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


RUN_ID = "run-1"
MANIFEST_DIGEST = _sha("manifest")
SCOPE = ScopeIdentity(ScopeKind.RUN, RUN_ID)


def _receipt(
    *,
    with_evidence: bool = True,
    run_id: str = RUN_ID,
) -> RunControlReceipt:
    evidence = None
    action = RunControlAction.RUN
    evidence_validity = RunEvidenceValidity.NOT_OBSERVED
    if with_evidence:
        artifact = RunArtifactSnapshotReceipt(
            run_id,
            "evidence/bundle-1/manifest.json",
            RunArtifactKind.EVIDENCE,
            _sha("generation"),
            _sha("manifest-content"),
            10,
            None,
        )
        evidence = EvidenceBundleReceipt(
            "bundle-1",
            run_id,
            MANIFEST_DIGEST,
            artifact,
        )
        action = RunControlAction.EVIDENCE
        evidence_validity = RunEvidenceValidity.FINALIZED_VALID

    return RunControlReceipt(
        action=action,
        run_id=run_id,
        run_identity_digest=_sha(f"identity:{run_id}"),
        run_manifest_digest=MANIFEST_DIGEST,
        phase=RunControlPhase.RUNNING,
        machine_cut=MachineCut(
            f"research-run:{run_id}",
            3,
            _sha(f"commit:{run_id}"),
            _sha(f"state:{run_id}"),
            _sha("program"),
        ),
        latest_checkpoint_id=None,
        checkpoint_manifest_digest=None,
        pending_operation=None,
        evidence_bundle_receipt=evidence,
        outcomes=RunOutcomeProjection(
            RunExecutionOutcome.IN_PROGRESS,
            RunTaskOutcome.NOT_EVALUATED,
            evidence_validity,
            RunScientificValidity.NOT_EVALUATED,
        ),
    )


class _Port:
    def __init__(self, receipt: RunControlReceipt | None = None) -> None:
        self.receipt = receipt

    def execute(self, request):
        assert request.target == RunControlTarget(
            RUN_ID,
            MANIFEST_DIGEST,
        )
        if self.receipt is None:
            raise RunControlNotFound("missing run control")
        return self.receipt


def test_run_control_source_projects_machine_backed_run_and_evidence() -> None:
    source = RunControlResearchResultSource(
        _Port(_receipt()),
        run_id=RUN_ID,
        run_manifest_digest=MANIFEST_DIGEST,
        scope=SCOPE,
    )
    query = ResearchResultQuery(
        dimensions=(
            ResearchDimension(
                ResearchDimensionKind.RUN,
                RUN_ID,
            ),
        ),
        kinds=(
            ResearchResultKind.RUN,
            ResearchResultKind.EVIDENCE,
        ),
    )
    first = source.snapshot(query)
    second = source.snapshot(query)
    assert first.source_id == source.source_id
    assert first.cut == second.cut
    assert {
        row.reference.kind for row in first.records
    } == {
        ResearchResultKind.RUN,
        ResearchResultKind.EVIDENCE,
    }
    run = next(
        row
        for row in first.records
        if row.reference.kind is ResearchResultKind.RUN
    )
    evidence = next(
        row
        for row in first.records
        if row.reference.kind is ResearchResultKind.EVIDENCE
    )
    assert run.content_sha256 == _receipt().receipt_digest
    assert evidence.lineage == (run.reference,)


def test_run_control_source_reports_missing_machine_authority_as_unavailable() -> None:
    source = RunControlResearchResultSource(
        _Port(),
        run_id=RUN_ID,
        run_manifest_digest=MANIFEST_DIGEST,
        scope=SCOPE,
    )
    from noetrium_platform.evidence.data.query.cross.composition import compose

    page = compose((source,)).query(
        ResearchResultQuery(kinds=(ResearchResultKind.RUN,))
    )
    assert page.complete is False
    assert page.records == ()
    assert (
        page.sources[0].disposition
        is ResearchSourceDisposition.UNAVAILABLE
    )
    assert (
        page.sources[0].diagnostic_code
        == "RUN_CONTROL_NOT_FOUND"
    )


def test_run_control_source_rejects_scope_and_machine_identity_drift() -> None:
    with pytest.raises(ValueError):
        RunControlResearchResultSource(
            _Port(_receipt(with_evidence=False)),
            run_id=RUN_ID,
            run_manifest_digest=MANIFEST_DIGEST,
            scope=ScopeIdentity(ScopeKind.STUDY, "study-1"),
        )

    source = RunControlResearchResultSource(
        _Port(_receipt(with_evidence=False, run_id="foreign-run")),
        run_id=RUN_ID,
        run_manifest_digest=MANIFEST_DIGEST,
        scope=SCOPE,
    )
    with pytest.raises(RuntimeError, match="identity"):
        source.snapshot(ResearchResultQuery())
