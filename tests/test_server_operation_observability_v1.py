from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from threading import Event, Thread

import pytest

from noetrium_platform.foundation.kernel.event import (
    event_field,
    event_ref,
    events_independent,
)

_PROFILE_DIGEST = "1" * 64
_OTHER_PROFILE_DIGEST = "2" * 64

from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationFinished,
    ServerOperationKind,
    ServerOperationRecord,
    ServerOperationStarted,
    ServerOperationState,
    ServerOperationResolved,
    ServerOperationResolution,
    ServerOperationReconciliationRequired,
    ServerOperationTransitionConflict,
    ServerMutationBusy,
    ServerTransportBusy,
)
from noetrium_platform.infrastructure.lifecycle.server.providers import (
    ObservedServerConnection,
    ObservedServerFileTransfer,
)
from noetrium_platform.infrastructure.lifecycle.server.runtime import ServerOperationEventIntegrityError
from tests._concurrency_support import server_operation_event_store as ServerOperationEventStore
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerConnectionProfile,
    ServerFileTransferResult,
)


class FakeJournal:
    def __init__(self) -> None:
        self.started: list[ServerOperationStarted] = []
        self.finished: list[ServerOperationFinished] = []

    def record_started(self, event: ServerOperationStarted) -> None:
        self.started.append(event)

    def record_finished(self, event: ServerOperationFinished) -> None:
        self.finished.append(event)

    def mutation_lock(self, *, server_id: str):
        del server_id
        return nullcontext()

    def transport_lock(self, *, server_id: str):
        del server_id
        return nullcontext()

    def pending_operations(self, *, server_id=None):
        del server_id
        return ()


class FakeConnection:
    profile = ServerConnectionProfile("server-a", "research.example", 60320, "ubuntu")

    def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
        del effect
        return ServerCommandResult(
            self.profile.server_id,
            command,
            0,
            "ok\n",
            "",
            duration_seconds=0.25,
            stdout_bytes=3,
        )

    def interactive_argv(self, command: str, *, allocate_tty: bool = False) -> tuple[str, ...]:
        return ("ssh", "-tt" if allocate_tty else "-T", command)

    def run_interactive(self, argv: tuple[str, ...]) -> int:
        assert argv[0] == "ssh"
        return 0


class FakeTransfer:
    profile = ServerConnectionProfile("server-a", "research.example", 60320, "ubuntu")

    def upload(self, local_path: str, remote_path: str, *, interactive: bool = False) -> ServerFileTransferResult:
        return ServerFileTransferResult(
            self.profile.server_id,
            local_path,
            remote_path,
            0,
            "",
            "",
            duration_seconds=0.5,
        )

    def download(self, remote_path: str, local_path: str, *, interactive: bool = False) -> ServerFileTransferResult:
        return ServerFileTransferResult(
            self.profile.server_id,
            local_path,
            remote_path,
            0,
            "",
            "",
            duration_seconds=0.5,
        )


class FailedConnection(FakeConnection):
    def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
        del interactive, effect
        return ServerCommandResult(self.profile.server_id, command, 23, "", "remote failed")


def test_observed_connection_records_correlation_without_raw_command() -> None:
    journal = FakeJournal()
    result = ObservedServerConnection(FakeConnection(), journal).execute(
        "printf 'private-looking payload'"
    )
    assert result.succeeded
    assert len(journal.started) == 1
    assert len(journal.finished) == 1
    assert journal.started[0].kind == ServerOperationKind.COMMAND
    assert journal.finished[0].state == ServerOperationState.SUCCEEDED
    assert journal.started[0].request_digest != "printf 'private-looking payload'"


def test_observed_connection_normalizes_unclassified_nonzero_provider_result() -> None:
    journal = FakeJournal()
    result = ObservedServerConnection(FailedConnection(), journal).execute("false")
    assert not result.succeeded
    assert journal.finished[0].failure_kind == "remote_exit"


def test_observed_connection_persists_redacted_diagnostic_preview(tmp_path: Path) -> None:
    class SecretConnection(FakeConnection):
        def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
            del interactive, effect
            return ServerCommandResult(
                self.profile.server_id,
                command,
                23,
                "password=hidden token=secret-value",
                "remote failure",
            )

    journal = ServerOperationEventStore(tmp_path / "server-operations.jsonl")
    result = ObservedServerConnection(SecretConnection(), journal).execute("false")
    assert not result.succeeded
    record = journal.recent_operations(1)[0]
    assert record.finished is not None
    assert "hidden" not in record.finished.stdout_preview
    assert "secret-value" not in record.finished.stdout_preview
    assert "<REDACTED>" in record.finished.stdout_preview


def test_observed_mutation_is_blocked_by_an_unreconciled_effect(tmp_path: Path) -> None:
    journal = ServerOperationEventStore(tmp_path / "server-operations.jsonl")
    journal.record_started(
        ServerOperationStarted(
            "op-pending",
            "server-a",
            ServerOperationKind.FILE_UPLOAD,
            "b" * 64,
            1.0,
            False,
            effect=ServerOperationEffect.MUTATION,
        )
    )
    with pytest.raises(ServerOperationReconciliationRequired, match="op-pending"):
        ObservedServerConnection(FakeConnection(), journal).execute(
            "touch /srv/state",
            effect=ServerOperationEffect.MUTATION,
        )
    assert len(journal.recent_operations()) == 1


def test_observed_read_fails_fast_while_another_controller_owns_transport(tmp_path: Path) -> None:
    journal = ServerOperationEventStore(tmp_path / "server-operations.jsonl")
    connection = ObservedServerConnection(FakeConnection(), journal)
    with journal.transport_lock(server_id="server-a"):
        with pytest.raises(ServerTransportBusy, match="server-a"):
            connection.execute("hostname", effect=ServerOperationEffect.OBSERVATION)
    assert journal.recent_operations() == ()


def test_observed_transfer_records_failure_boundary(tmp_path: Path) -> None:
    local = tmp_path / "release.zip"
    local.write_bytes(b"release")
    journal = FakeJournal()
    result = ObservedServerFileTransfer(FakeTransfer(), journal).upload(
        str(local), "/data/releases/release.zip"
    )
    assert result.succeeded
    assert journal.started[0].kind == ServerOperationKind.FILE_UPLOAD
    assert journal.finished[0].return_code == 0


def test_observed_download_uses_the_same_operation_ledger(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    journal = FakeJournal()
    result = ObservedServerFileTransfer(FakeTransfer(), journal).download(
        "/data/results/result.json", str(target)
    )
    assert result.succeeded
    assert journal.started[0].kind == ServerOperationKind.FILE_DOWNLOAD
    assert journal.finished[0].state == ServerOperationState.SUCCEEDED


def test_observed_interactive_attach_is_journaled_without_owning_subprocess() -> None:
    journal = FakeJournal()
    result = ObservedServerConnection(FakeConnection(), journal).run_interactive(
        ("ssh", "-tt", "ubuntu@research.example", "tmux attach")
    )
    assert result == 0
    assert journal.started[0].kind == ServerOperationKind.INTERACTIVE_ATTACH
    assert journal.finished[0].state == ServerOperationState.SUCCEEDED


def _store(tmp_path: Path) -> ServerOperationEventStore:
    return ServerOperationEventStore(tmp_path / "server-operation-events")


def _started_mutation(operation_id: str, *, profile: str = _PROFILE_DIGEST, server_id: str = "server-a") -> ServerOperationStarted:
    return ServerOperationStarted(
        operation_id,
        server_id,
        ServerOperationKind.FILE_UPLOAD,
        "e" * 64,
        1.0,
        False,
        profile,
        ServerOperationEffect.MUTATION,
    )


def _finished_mutation(operation_id: str, *, profile: str = _PROFILE_DIGEST, server_id: str = "server-a") -> ServerOperationFinished:
    return ServerOperationFinished(
        operation_id,
        server_id,
        ServerOperationKind.FILE_UPLOAD,
        "e" * 64,
        ServerOperationState.SUCCEEDED,
        2.0,
        1.0,
        0,
        "none",
        0,
        0,
        profile_digest=profile,
        effect=ServerOperationEffect.MUTATION,
    )


def test_server_operation_events_are_replayable_and_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    started = ServerOperationStarted(
        "op-1", "server-a", ServerOperationKind.COMMAND, "a" * 64,
        1.0, False, effect=ServerOperationEffect.OBSERVATION,
    )
    finished = ServerOperationFinished(
        "op-1", "server-a", ServerOperationKind.COMMAND, "a" * 64,
        ServerOperationState.FAILED, 2.0, 1.0, 255, "remote_exit", 3, 4,
        effect=ServerOperationEffect.OBSERVATION,
    )
    store.record_started(started)
    store.record_finished(finished)

    reopened = ServerOperationEventStore(store.root)
    assert reopened.read_operation("op-1") == ServerOperationRecord(started, finished)
    assert reopened.pending_operations() == ()
    assert reopened.recent_operations(1)[0].operation_id == "op-1"


def test_server_operation_causal_chain_has_local_generation_and_parent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-chain"))
    store.record_finished(_finished_mutation("op-chain"))
    trace = store.event_trace("op-chain")

    assert [event_field(row, "generation") for row in trace] == [1, 2]
    assert [event_field(row, "phase") for row in trace] == ["started", "finished"]
    assert [event_field(row, "modality").value for row in trace] == ["declared", "observed"]
    assert trace[0].refs("causal-parent") == ()
    assert trace[1].refs("causal-parent") == (event_ref(trace[0]),)


def test_independent_server_operations_have_no_synthetic_global_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-a", server_id="server-a"))
    store.record_started(_started_mutation("op-b", server_id="server-b"))
    left = store.event_trace("op-a")[0]
    right = store.event_trace("op-b")[0]

    assert event_field(left, "authority_domain") != event_field(right, "authority_domain")
    assert left.refs("causal-parent") == right.refs("causal-parent") == ()
    assert events_independent(left, right)


def test_unfinished_mutation_is_reconciliation_required(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-pending"))
    pending = store.pending_operations()
    assert [row.operation_id for row in pending] == ["op-pending"]
    assert pending[0].effect_uncertain


def test_pending_projection_is_scoped_by_server(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-a", server_id="server-a"))
    store.record_started(_started_mutation("op-b", server_id="server-b"))
    assert [row.operation_id for row in store.pending_operations(server_id="server-a")] == ["op-a"]
    assert [row.operation_id for row in store.pending_operations(server_id="server-b")] == ["op-b"]


def test_resolution_is_evidenced_terminal_transition(tmp_path: Path) -> None:
    store = _store(tmp_path)
    started = _started_mutation("op-resolve")
    store.record_started(started)
    store.record_resolved(
        ServerOperationResolved(
            started.operation_id,
            started.server_id,
            started.kind,
            started.request_digest,
            ServerOperationResolution.EFFECT_NOT_APPLIED,
            2.0,
            "remote-check:op-resolve",
            "c" * 64,
            started.profile_digest,
        )
    )
    trace = store.event_trace(started.operation_id)
    assert event_field(trace[-1], "modality").value == "evidenced"
    assert store.pending_operations() == ()


def test_finished_timeout_remains_effect_uncertain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(
        ServerOperationStarted(
            "op-timeout", "server-a", ServerOperationKind.COMMAND, "d" * 64,
            1.0, False, effect=ServerOperationEffect.MUTATION,
        )
    )
    store.record_finished(
        ServerOperationFinished(
            "op-timeout", "server-a", ServerOperationKind.COMMAND, "d" * 64,
            ServerOperationState.TIMED_OUT, 2.0, 1.0, 124, "timeout", 0, 0,
            effect=ServerOperationEffect.MUTATION,
        )
    )
    assert [row.operation_id for row in store.pending_operations()] == ["op-timeout"]


def test_duplicate_finish_is_rejected_without_appending_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-duplicate-finish"))
    finished = _finished_mutation("op-duplicate-finish")
    store.record_finished(finished)
    before = store.event_trace("op-duplicate-finish")
    with pytest.raises(ServerOperationTransitionConflict, match="already finished"):
        store.record_finished(finished)
    assert store.event_trace("op-duplicate-finish") == before


def test_profile_drift_is_rejected_before_event_append(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-profile"))
    with pytest.raises(ServerOperationTransitionConflict, match="identity"):
        store.record_finished(_finished_mutation("op-profile", profile=_OTHER_PROFILE_DIGEST))
    assert len(store.event_trace("op-profile")) == 1


def test_finish_after_resolution_is_rejected_before_event_append(tmp_path: Path) -> None:
    store = _store(tmp_path)
    started = _started_mutation("op-resolved-first")
    store.record_started(started)
    store.record_resolved(
        ServerOperationResolved(
            started.operation_id, started.server_id, started.kind,
            started.request_digest, ServerOperationResolution.EFFECT_NOT_APPLIED,
            2.0, "remote-check:resolved", "c" * 64, started.profile_digest,
        )
    )
    before = store.event_trace(started.operation_id)
    with pytest.raises(ServerOperationTransitionConflict, match="already reconciled"):
        store.record_finished(_finished_mutation(started.operation_id))
    assert store.event_trace(started.operation_id) == before


def test_mutation_lock_is_stable_per_server_and_separate_between_servers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_a = store.mutation_lock(server_id="server-a")
    second_a = store.mutation_lock(server_id="server-a")
    lock_b = store.mutation_lock(server_id="server-b")
    assert first_a.path == second_a.path
    assert first_a.path != lock_b.path


def test_mutation_lock_fails_fast_when_owned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.mutation_lock(server_id="server-a")
    second = store.mutation_lock(server_id="server-a")
    with first:
        with pytest.raises(ServerMutationBusy, match="server-a"):
            with second:
                pass


def test_corrupt_event_unit_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-tamper"))
    path = store._event_paths("op-tamper")[0]
    path.write_bytes(b"not-a-unit")
    with pytest.raises(ServerOperationEventIntegrityError, match="corrupt"):
        store.read_operation("op-tamper")


def test_missing_causal_prefix_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_started(_started_mutation("op-prefix"))
    store.record_finished(_finished_mutation("op-prefix"))
    first, second = store._event_paths("op-prefix")
    first.unlink()
    assert second.exists()
    with pytest.raises(ServerOperationEventIntegrityError):
        store.read_operation("op-prefix")


@pytest.mark.parametrize(
    "field,value",
    (
        ("server_id", "unsafe server"),
        ("request_digest", "not-a-digest"),
        ("profile_digest", "not-a-digest"),
    ),
)
def test_event_store_rejects_invalid_durable_identity_before_write(
    tmp_path: Path, field: str, value: str
) -> None:
    values = {
        "operation_id": "op-invalid-identity",
        "server_id": "server-a",
        "request_digest": "a" * 64,
        "profile_digest": _PROFILE_DIGEST,
    }
    values[field] = value
    event = ServerOperationStarted(
        values["operation_id"], values["server_id"], ServerOperationKind.COMMAND,
        values["request_digest"], 1.0, False, values["profile_digest"],
        ServerOperationEffect.MUTATION,
    )
    store = _store(tmp_path)
    with pytest.raises(ServerOperationEventIntegrityError):
        store.record_started(event)
    assert tuple(store.root.iterdir()) == ()


@pytest.mark.parametrize(
    "state,return_code,failure_kind,error_type,error_digest",
    (
        (ServerOperationState.SUCCEEDED, 1, "none", None, None),
        (ServerOperationState.SUCCEEDED, 0, "remote_exit", None, None),
        (ServerOperationState.SUCCEEDED, 0, "none", "RuntimeError", "f" * 64),
        (ServerOperationState.FAILED, 1, "none", None, None),
        (ServerOperationState.TIMED_OUT, 124, "network", None, None),
        (ServerOperationState.FAILED, 1, "remote_exit", "RuntimeError", None),
        (ServerOperationState.FAILED, 1, "remote_exit", "RuntimeError", "bad-digest"),
    ),
)
def test_event_store_rejects_impossible_finished_evidence(
    tmp_path: Path,
    state: ServerOperationState,
    return_code: int,
    failure_kind: str,
    error_type: str | None,
    error_digest: str | None,
) -> None:
    store = _store(tmp_path)
    operation_id = "op-invalid-finish"
    store.record_started(_started_mutation(operation_id))
    event = ServerOperationFinished(
        operation_id, "server-a", ServerOperationKind.FILE_UPLOAD, "e" * 64,
        state, 2.0, 1.0, return_code, failure_kind, 0, 0,
        error_type, error_digest, profile_digest=_PROFILE_DIGEST,
        effect=ServerOperationEffect.MUTATION,
    )
    with pytest.raises(ServerOperationEventIntegrityError):
        store.record_finished(event)
    assert len(store.event_trace(operation_id)) == 1
