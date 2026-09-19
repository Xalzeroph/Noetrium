from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests_support import frozen_runtime_manifest
from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    MachineIntegrityError,
)
from noetrium_platform.infrastructure.reliability.effect.api import (
    EffectReconciliationDisposition,
    EffectReconciliationProof,
)
from noetrium_platform.research.execution.decision.cycle_identity import (
    DecisionCycleIdentity,
)
from noetrium_platform.research.execution.operation.api import (
    project_effect_reconciliation,
)
from noetrium_platform.research.experimentation.checkpoint.api.contracts import (
    RunCheckpointBundle,
    RunCheckpointManifest,
)
from noetrium_platform.research.experimentation.run.api.artifacts import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
    RunArtifactVerificationError,
)
from noetrium_platform.research.experimentation.run.control.api import (
    RunControlAction,
    RunControlActionFailure,
    RunControlConflict,
    RunControlIntegrityError,
    RunControlPhase,
    RunControlRequest,
    RunControlStaleRevision,
    RunControlTarget,
    RunControlTransitionOutcome,
)
from noetrium_platform.research.experimentation.run.control.composition.factory import (
    build_durable_run_control,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api.evidence import (
    EvidenceBundleReceipt,
)


class _Lifecycle:
    def __init__(
        self,
        *,
        run_phase: RunControlPhase = RunControlPhase.RUNNING,
        stop_phase: RunControlPhase = RunControlPhase.STOPPED,
        resume_phase: RunControlPhase = RunControlPhase.RUNNING,
        run_error: BaseException | None = None,
    ) -> None:
        self.run_phase = run_phase
        self.stop_phase = stop_phase
        self.resume_phase = resume_phase
        self.run_error = run_error
        self.run_calls = 0
        self.stop_calls = 0
        self.resume_calls = 0

    def run(self, identity, manifest, *, operation_id):
        del identity, manifest
        self.run_calls += 1
        if self.run_error is not None:
            raise self.run_error
        return RunControlTransitionOutcome(self.run_phase)

    def stop(self, identity, manifest, *, operation_id):
        del identity, manifest, operation_id
        self.stop_calls += 1
        return RunControlTransitionOutcome(self.stop_phase)

    def resume(
        self,
        identity,
        manifest,
        checkpoint,
        restore_cycle_identity,
        *,
        operation_id,
    ):
        del identity, manifest, checkpoint, restore_cycle_identity, operation_id
        self.resume_calls += 1
        return RunControlTransitionOutcome(self.resume_phase)


class _CheckpointStore:
    def __init__(self, manifest: RunCheckpointManifest) -> None:
        self.manifest = manifest

    def load(self, checkpoint_id: str) -> RunCheckpointBundle:
        if checkpoint_id != self.manifest.checkpoint_id:
            raise KeyError(checkpoint_id)
        return RunCheckpointBundle(self.manifest, ())


class _Reconciliation:
    def __init__(self, proof: EffectReconciliationProof) -> None:
        self.proof = proof
        self.calls = 0

    def reconcile(self, identity, manifest, prepared_operation):
        del identity, manifest
        self.calls += 1
        proof = self.proof
        effect = proof.effect
        request_id = (
            prepared_operation.operation_id
            if proof.request_id == "AUTO"
            else proof.request_id
        )
        if effect is not None and proof.request_id == "AUTO":
            effect = EffectReceipt(
                effect.effect_id,
                prepared_operation.operation_id,
                effect.effect_class,
                effect.certainty,
                effect.provider_instance_id,
                effect.verification_required,
                effect.before_artifact,
                effect.after_artifact,
                effect.provider_receipt,
            )
        return project_effect_reconciliation(
            EffectReconciliationProof(
                request_id,
                proof.disposition,
                effect,
                proof.diagnostics,
            )
        )


class _Evidence:
    def __init__(self, receipt: EvidenceBundleReceipt | None = None) -> None:
        self.receipt = receipt

    def evidence(self, identity, manifest):
        del identity, manifest
        return self.receipt


class _Verifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def verify_finalized(self, receipt):
        if self.fail:
            raise RunArtifactVerificationError("not finalized")
        return receipt


@dataclass(frozen=True)
class _Fixture:
    identity: RunIdentity
    manifest: object
    cycle: DecisionCycleIdentity
    checkpoint: RunCheckpointManifest


def _fixture() -> _Fixture:
    identity = RunIdentity("run-1", "session-1", "trace-1")
    manifest = frozen_runtime_manifest(experiment_spec_digest="study-1")
    cycle = DecisionCycleIdentity(
        "run-1",
        "cycle-1",
        "session-1",
        "task-1",
        "trace-1",
    )
    checkpoint = RunCheckpointManifest(
        checkpoint_id="checkpoint-1",
        schema_version="1",
        experiment_spec_digest="study-1",
        run_id="run-1",
        session_id="session-1",
        decision_cycle_id="cycle-1",
        cycle_identity_digest=cycle.digest(),
        participant_snapshots=(),
    )
    return _Fixture(identity, manifest, cycle, checkpoint)


def _journal(root: Path) -> DirectoryMachineJournal:
    return DirectoryMachineJournal(root / "machine-journal")


def _target(fx: _Fixture, revision: int | None) -> RunControlTarget:
    return RunControlTarget(
        fx.identity.run_id,
        fx.manifest.digest(),
        revision,
    )


def _control(
    root: Path,
    fx: _Fixture,
    *,
    lifecycle: _Lifecycle | None = None,
    reconciliation: _Reconciliation | None = None,
    evidence: _Evidence | None = None,
    verifier: _Verifier | None = None,
    checkpoint: RunCheckpointManifest | None = None,
):
    return build_durable_run_control(
        identity=fx.identity,
        manifest=fx.manifest,
        run_machine_journal=_journal(root),
        lifecycle=lifecycle or _Lifecycle(),
        checkpoint_store=_CheckpointStore(checkpoint or fx.checkpoint),
        reconciliation=reconciliation
        or _Reconciliation(
            EffectReconciliationProof(
                "reconcile-1",
                EffectReconciliationDisposition.NOT_APPLIED,
                None,
                {},
            )
        ),
        evidence=evidence or _Evidence(),
        artifact_verifier=verifier or _Verifier(),
    )


def _evidence_receipt(
    fx: _Fixture,
    *,
    run_id: str = "run-1",
) -> EvidenceBundleReceipt:
    artifact = RunArtifactSnapshotReceipt(
        run_id=run_id,
        artifact_ref="evidence/bundle-1/manifest.json",
        artifact_kind=RunArtifactKind.EVIDENCE,
        generation="a" * 64,
        content_sha256="b" * 64,
        byte_size=10,
        record_count=None,
    )
    return EvidenceBundleReceipt(
        "bundle-1",
        run_id,
        fx.manifest.digest(),
        artifact,
    )


def test_run_control_reopens_same_machine_cut_from_durable_journal(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    first = _control(tmp_path, fx)
    initial = first.execute(
        RunControlRequest(
            RunControlAction.INSPECT,
            _target(fx, None),
        )
    )
    assert initial.phase is RunControlPhase.CREATED
    assert initial.control_revision == 1

    running = first.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    assert running.phase is RunControlPhase.RUNNING
    assert running.pending_operation is None
    assert running.control_revision > initial.control_revision

    reopened = _control(tmp_path, fx).execute(
        RunControlRequest(
            RunControlAction.INSPECT,
            _target(fx, running.control_revision),
        )
    )
    assert reopened.machine_cut == running.machine_cut
    assert reopened.receipt_digest == running.receipt_digest


def test_stale_revision_fails_before_external_lifecycle_effect(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    lifecycle = _Lifecycle()
    control = _control(tmp_path, fx, lifecycle=lifecycle)
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    running = control.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    with pytest.raises(RunControlStaleRevision):
        control.execute(
            RunControlRequest(
                RunControlAction.STOP,
                _target(fx, initial.control_revision),
            )
        )
    assert running.phase is RunControlPhase.RUNNING
    assert lifecycle.stop_calls == 0


def test_uncertain_external_effect_is_prepared_in_run_machine_before_error(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    control = _control(
        tmp_path,
        fx,
        lifecycle=_Lifecycle(run_error=RuntimeError("uncertain")),
    )
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    with pytest.raises(RunControlActionFailure) as raised:
        control.execute(
            RunControlRequest(
                RunControlAction.RUN,
                _target(fx, initial.control_revision),
            )
        )
    receipt = raised.value.receipt
    assert receipt.phase is RunControlPhase.RECOVERY_REQUIRED
    assert receipt.pending_operation is not None
    assert receipt.pending_operation.action is RunControlAction.RUN

    reopened = _control(tmp_path, fx).execute(
        RunControlRequest(
            RunControlAction.INSPECT,
            _target(fx, receipt.control_revision),
        )
    )
    assert reopened.machine_cut == receipt.machine_cut
    assert reopened.pending_operation == receipt.pending_operation


def test_confirmed_reconciliation_resolves_machine_pending_operation(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    proof = EffectReconciliationProof(
        "AUTO",
        EffectReconciliationDisposition.APPLIED,
        EffectReceipt(
            "effect-1",
            "d" * 64,
            EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED,
        ),
        {},
    )
    control = _control(
        tmp_path,
        fx,
        lifecycle=_Lifecycle(
            run_phase=RunControlPhase.RECOVERY_REQUIRED
        ),
        reconciliation=_Reconciliation(proof),
    )
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    uncertain = control.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    assert uncertain.pending_operation is not None

    resolved = control.execute(
        RunControlRequest(
            RunControlAction.RECONCILE,
            _target(fx, uncertain.control_revision),
        )
    )
    assert resolved.phase is RunControlPhase.RUNNING
    assert resolved.pending_operation is None
    assert resolved.control_revision > uncertain.control_revision


def test_stop_and_resume_bind_exact_checkpoint_identity(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    control = _control(tmp_path, fx)
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    running = control.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    stopped = control.execute(
        RunControlRequest(
            RunControlAction.STOP,
            _target(fx, running.control_revision),
        )
    )
    assert stopped.phase is RunControlPhase.STOPPED

    resumed = control.execute(
        RunControlRequest(
            RunControlAction.RESUME,
            _target(fx, stopped.control_revision),
            restore_checkpoint_id=fx.checkpoint.checkpoint_id,
            restore_cycle_identity=fx.cycle,
        )
    )
    assert resumed.phase is RunControlPhase.RUNNING
    assert resumed.latest_checkpoint_id == fx.checkpoint.checkpoint_id
    assert (
        resumed.checkpoint_manifest_digest
        == fx.checkpoint.digest()
    )


def test_resume_rejects_foreign_checkpoint_identity(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    foreign = RunCheckpointManifest(
        checkpoint_id="checkpoint-1",
        schema_version="1",
        experiment_spec_digest="study-1",
        run_id="other-run",
        session_id="other-session",
        decision_cycle_id="cycle-1",
        cycle_identity_digest=fx.cycle.digest(),
        participant_snapshots=(),
    )
    control = _control(tmp_path, fx, checkpoint=foreign)
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    running = control.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    stopped = control.execute(
        RunControlRequest(
            RunControlAction.STOP,
            _target(fx, running.control_revision),
        )
    )
    with pytest.raises(RunControlIntegrityError, match="another run/session"):
        control.execute(
            RunControlRequest(
                RunControlAction.RESUME,
                _target(fx, stopped.control_revision),
                restore_checkpoint_id="checkpoint-1",
                restore_cycle_identity=fx.cycle,
            )
        )


def test_finalized_evidence_is_read_only_projection_over_same_machine_cut(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    base = _control(tmp_path, fx)
    initial = base.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    running = base.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    evidence = _evidence_receipt(fx)
    receipt = _control(
        tmp_path,
        fx,
        evidence=_Evidence(evidence),
    ).execute(
        RunControlRequest(
            RunControlAction.EVIDENCE,
            _target(fx, running.control_revision),
        )
    )
    assert receipt.evidence_bundle_receipt == evidence
    assert receipt.machine_cut == running.machine_cut


def test_unfinalized_evidence_fails_closed(tmp_path: Path) -> None:
    fx = _fixture()
    control = _control(
        tmp_path,
        fx,
        evidence=_Evidence(_evidence_receipt(fx)),
        verifier=_Verifier(fail=True),
    )
    with pytest.raises(
        RunControlIntegrityError,
        match="not finalized authority",
    ):
        control.execute(
            RunControlRequest(
                RunControlAction.EVIDENCE,
                _target(fx, None),
            )
        )


def test_corrupt_machine_journal_fails_closed(tmp_path: Path) -> None:
    fx = _fixture()
    control = _control(tmp_path, fx)
    initial = control.execute(
        RunControlRequest(RunControlAction.INSPECT, _target(fx, None))
    )
    control.execute(
        RunControlRequest(
            RunControlAction.RUN,
            _target(fx, initial.control_revision),
        )
    )
    (log,) = (tmp_path / "machine-journal" / "machines").glob(
        "*.journal"
    )
    rows = log.read_bytes().splitlines()
    document = json.loads(rows[-1])
    rows[-1] = json.dumps(
        document,
        sort_keys=False,
        indent=2,
    ).encode("utf-8")
    log.write_bytes(b"\n".join(rows) + b"\n")

    with pytest.raises(MachineIntegrityError):
        _control(tmp_path, fx)


def test_manifest_drift_is_rejected_without_new_control_authority(
    tmp_path: Path,
) -> None:
    fx = _fixture()
    control = _control(tmp_path, fx)
    with pytest.raises(RunControlConflict):
        control.execute(
            RunControlRequest(
                RunControlAction.RUN,
                RunControlTarget(
                    fx.identity.run_id,
                    "f" * 64,
                    1,
                ),
            )
        )
