from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from noetrium.contracts.json import canonical_digest, thaw_json
from noetrium.contracts.research import (
    EvidenceBundleReceipt,
    MachineCut,
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
    RunControlConflict,
    RunControlError,
    RunControlIntegrityError,
    RunControlPhase,
    RunControlReceipt,
    RunControlRequest,
    RunControlStaleRevision,
    RunEvidenceValidity,
    RunExecutionOutcome,
    RunOutcomeProjection,
    RunScientificValidity,
    RunTaskOutcome,
)
from noetrium.platform import (
    ResearchAction,
    ResearchFacade,
    bind_run_control_application,
)

RUN_ID = "__RUN_ID__"
RUN_MANIFEST_DIGEST = "__RUN_MANIFEST_DIGEST__"
CHECKPOINT_ID = "checkpoint-1"
PROGRAM_DIGEST = hashlib.sha256(
    b"noetrium:npe-reference:run-machine:v2"
).hexdigest()
CYCLE = {
    "run_id": RUN_ID,
    "decision_cycle_id": "cycle-1",
    "session_id": "session-1",
    "task_id": "task-1",
    "trace_id": "trace-1",
}
STATE_KEYS = frozenset({
    "revision",
    "phase",
    "latest_checkpoint_id",
    "checkpoint_manifest_digest",
    "cycle_identity_digest",
})


def _initial_state() -> dict[str, object]:
    return {
        "revision": 1,
        "phase": "created",
        "latest_checkpoint_id": None,
        "checkpoint_manifest_digest": None,
        "cycle_identity_digest": canonical_digest(CYCLE),
    }


def _content_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checkpoint_digest() -> str:
    return canonical_digest({
        "run_id": RUN_ID,
        "checkpoint_id": CHECKPOINT_ID,
        "cycle_identity_digest": canonical_digest(CYCLE),
    })


def _load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        state = _initial_state()
        _write_state(path, state)
        return state
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or frozenset(data) != STATE_KEYS:
        raise RunControlIntegrityError(
            "reference lifecycle state schema drifted"
        )
    if type(data["revision"]) is not int or data["revision"] < 1:
        raise RunControlIntegrityError(
            "reference lifecycle revision is invalid"
        )
    if data["phase"] not in {
        "created",
        "running",
        "stopped",
        "recovery_required",
        "completed",
        "failed",
        "closed",
    }:
        raise RunControlIntegrityError(
            "reference lifecycle phase is invalid"
        )
    return data


def _write_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=".noetrium-state-",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(
            handle,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(
                state,
                stream,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _machine_cut(state: dict[str, object]) -> MachineCut:
    revision = state["revision"]
    if type(revision) is not int:
        raise RunControlIntegrityError(
            "reference lifecycle revision is invalid"
        )
    state_digest = canonical_digest(state)
    commit_id = canonical_digest({
        "machine_id": f"research-run:{RUN_ID}",
        "revision": revision,
        "state_digest": state_digest,
        "program_digest": PROGRAM_DIGEST,
    })
    return MachineCut(
        f"research-run:{RUN_ID}",
        revision,
        commit_id,
        state_digest,
        PROGRAM_DIGEST,
    )


class ReferenceRunControl:
    """Clean-room public-contract fixture using MachineCut revision semantics."""

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path

    def _validate_target(
        self,
        request: RunControlRequest,
        state: dict[str, object],
    ) -> None:
        target = request.target
        if (
            target.run_id != RUN_ID
            or target.run_manifest_digest != RUN_MANIFEST_DIGEST
        ):
            raise RunControlConflict(
                "reference lifecycle target identity drifted"
            )
        expected = target.expected_revision
        if expected is not None and expected != state["revision"]:
            raise RunControlStaleRevision(
                "reference lifecycle expected revision is stale"
            )

    def _evidence(self, state: dict[str, object]):
        bundle_id = "npe-reference"
        artifact_ref = f"evidence/{bundle_id}/manifest.json"
        artifact_path = self._state_path.parent / artifact_ref
        if not artifact_path.is_file():
            return None
        raw = artifact_path.read_bytes()
        artifact = RunArtifactSnapshotReceipt(
            RUN_ID,
            artifact_ref,
            RunArtifactKind.EVIDENCE,
            canonical_digest({
                "run_id": RUN_ID,
                "revision": state["revision"],
            }),
            _content_digest(raw),
            len(raw),
            None,
        )
        return EvidenceBundleReceipt(
            bundle_id,
            RUN_ID,
            RUN_MANIFEST_DIGEST,
            artifact,
        )

    def _receipt(
        self,
        request: RunControlRequest,
        state: dict[str, object],
        *,
        evidence=None,
    ) -> RunControlReceipt:
        phase = RunControlPhase(state["phase"])
        execution = {
            RunControlPhase.CREATED: RunExecutionOutcome.NOT_STARTED,
            RunControlPhase.RUNNING: RunExecutionOutcome.IN_PROGRESS,
            RunControlPhase.STOPPED: RunExecutionOutcome.STOPPED,
            RunControlPhase.RECOVERY_REQUIRED:
                RunExecutionOutcome.RECOVERY_REQUIRED,
            RunControlPhase.COMPLETED: RunExecutionOutcome.SUCCEEDED,
            RunControlPhase.FAILED: RunExecutionOutcome.FAILED,
            RunControlPhase.CLOSED: RunExecutionOutcome.CLOSED,
        }[phase]
        if evidence is None and request.action.value == "evidence":
            evidence_validity = RunEvidenceValidity.NOT_FINALIZED
        elif evidence is None:
            evidence_validity = RunEvidenceValidity.NOT_OBSERVED
        else:
            evidence_validity = RunEvidenceValidity.FINALIZED_VALID
        return RunControlReceipt(
            request.action,
            RUN_ID,
            canonical_digest({"run_id": RUN_ID}),
            RUN_MANIFEST_DIGEST,
            phase,
            _machine_cut(state),
            state["latest_checkpoint_id"],
            state["checkpoint_manifest_digest"],
            None,
            evidence,
            RunOutcomeProjection(
                execution,
                RunTaskOutcome.NOT_EVALUATED,
                evidence_validity,
                RunScientificValidity.NOT_EVALUATED,
            ),
        )

    def _transition(
        self,
        request: RunControlRequest,
        state: dict[str, object],
        phase: str,
    ) -> RunControlReceipt:
        revision = state["revision"]
        if type(revision) is not int:
            raise RunControlIntegrityError(
                "reference lifecycle revision is invalid"
            )
        # External lifecycle actions use prepare + resolve, exactly as RunMachine.
        state["revision"] = revision + 2
        state["phase"] = phase
        _write_state(self._state_path, state)
        return self._receipt(request, state)

    def execute(self, request: RunControlRequest) -> RunControlReceipt:
        state = _load_state(self._state_path)
        self._validate_target(request, state)
        action = request.action.value

        if action in {"inspect", "reconcile"}:
            return self._receipt(request, state)

        if action == "run":
            if state["phase"] == "running":
                return self._receipt(request, state)
            if state["phase"] != "created":
                raise RunControlConflict(
                    "reference lifecycle cannot run from current phase"
                )
            return self._transition(request, state, "running")

        if action == "stop":
            if state["phase"] != "running":
                raise RunControlConflict(
                    "reference lifecycle can stop only while running"
                )
            return self._transition(request, state, "stopped")

        if action == "resume":
            cycle = request.restore_cycle_identity
            if (
                state["phase"] != "stopped"
                or request.restore_checkpoint_id != CHECKPOINT_ID
            ):
                raise RunControlConflict(
                    "reference lifecycle restore checkpoint is not current"
                )
            if (
                cycle is None
                or cycle.run_id != RUN_ID
                or cycle.session_id != CYCLE["session_id"]
                or cycle.decision_cycle_id != CYCLE["decision_cycle_id"]
                or cycle.task_id != CYCLE["task_id"]
                or cycle.trace_id != CYCLE["trace_id"]
                or cycle.digest() != canonical_digest(CYCLE)
            ):
                raise RunControlIntegrityError(
                    "reference lifecycle restore cycle identity drifted"
                )
            state["latest_checkpoint_id"] = CHECKPOINT_ID
            state["checkpoint_manifest_digest"] = _checkpoint_digest()
            return self._transition(request, state, "running")

        if action == "evidence":
            bundle_id = "npe-reference"
            artifact_path = (
                self._state_path.parent
                / "evidence"
                / bundle_id
                / "manifest.json"
            )
            if not artifact_path.is_file():
                payload = {
                    "bundle_id": bundle_id,
                    "revision": state["revision"],
                    "run_id": RUN_ID,
                    "run_manifest_digest": RUN_MANIFEST_DIGEST,
                    "machine_cut_digest": _machine_cut(state).cut_digest,
                }
                raw = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                artifact_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                artifact_path.write_bytes(raw)
            return self._receipt(
                request,
                state,
                evidence=self._evidence(state),
            )

        raise RunControlError(
            "reference lifecycle action is unsupported"
        )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        raise ValueError(
            "reference lifecycle requires action, state path and JSON payload"
        )
    action = ResearchAction(arguments[0])
    state_path = Path(arguments[1]).resolve()
    payload = json.loads(arguments[2])
    application = bind_run_control_application(
        ReferenceRunControl(state_path),
        run_id=RUN_ID,
        run_manifest_digest=RUN_MANIFEST_DIGEST,
    )
    facade = ResearchFacade(application)
    result = getattr(facade, action.value)(RUN_ID, payload)
    print(json.dumps({
        "ok": True,
        "action": result.action.value,
        "state": result.state,
        "payload": thaw_json(result.payload),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException as exc:
        print(json.dumps({
            "error": type(exc).__name__,
            "message": str(exc),
            "ok": False,
        }, sort_keys=True))
        exit_code = 1
    raise SystemExit(exit_code)
