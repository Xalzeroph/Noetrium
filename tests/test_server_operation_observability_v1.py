from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from threading import Event, Thread

import pytest

_PROFILE_DIGEST = "1" * 64
_OTHER_PROFILE_DIGEST = "2" * 64

from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationFinished,
    ServerOperationKind,
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
from noetrium_platform.infrastructure.lifecycle.server.runtime import ServerOperationJournalIntegrityError
from tests._concurrency_support import server_operation_journal as JsonlServerOperationJournal
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

    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
    result = ObservedServerConnection(SecretConnection(), journal).execute("false")
    assert not result.succeeded
    record = journal.recent_operations(1)[0]
    assert record.finished is not None
    assert "hidden" not in record.finished.stdout_preview
    assert "secret-value" not in record.finished.stdout_preview
    assert "<REDACTED>" in record.finished.stdout_preview


def test_observed_mutation_is_blocked_by_an_unreconciled_effect(tmp_path: Path) -> None:
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
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
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
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


def test_jsonl_journal_is_replayable_and_durable(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(ServerOperationStarted("op-1", "server-a", ServerOperationKind.COMMAND, "a" * 64, 1.0, False, effect=ServerOperationEffect.OBSERVATION))
    journal.record_finished(ServerOperationFinished("op-1", "server-a", ServerOperationKind.COMMAND, "a" * 64, ServerOperationState.FAILED, 2.0, 1.0, 255, "remote_exit", 3, 4, effect=ServerOperationEffect.OBSERVATION))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["started", "finished"]
    assert rows[1]["failure_kind"] == "remote_exit"
    record = journal.read_operation("op-1")
    assert record is not None
    assert record.finished is not None
    assert not record.effect_uncertain
    assert journal.pending_operations() == ()
    assert journal.recent_operations(1)[0].operation_id == "op-1"


def test_jsonl_journal_exposes_unfinished_effect_as_reconciliation_required(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(
        ServerOperationStarted("op-pending", "server-a", ServerOperationKind.FILE_UPLOAD, "b" * 64, 1.0, False, effect=ServerOperationEffect.MUTATION)
    )

    pending = journal.pending_operations()
    assert [record.operation_id for record in pending] == ["op-pending"]
    assert pending[0].state == ServerOperationState.STARTED
    assert pending[0].effect_uncertain


def test_jsonl_journal_scopes_recovery_to_the_requested_server(tmp_path: Path) -> None:
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
    for operation_id, server_id in (("op-a", "server-a"), ("op-b", "server-b")):
        journal.record_started(
            ServerOperationStarted(
                operation_id,
                server_id,
                ServerOperationKind.COMMAND,
                ("a" if operation_id == "op-a" else "b") * 64,
                1.0,
                False,
                effect=ServerOperationEffect.MUTATION,
            )
        )
    assert [record.operation_id for record in journal.pending_operations(server_id="server-a")] == ["op-a"]
    assert [record.operation_id for record in journal.pending_operations(server_id="server-b")] == ["op-b"]
    assert [record.operation_id for record in journal.recent_operations(server_id="server-a")] == ["op-a"]


def test_jsonl_mutation_lock_is_stable_per_server_and_separate_between_servers(tmp_path: Path) -> None:
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
    first_a = journal.mutation_lock(server_id="server-a")
    second_a = journal.mutation_lock(server_id="server-a")
    lock_b = journal.mutation_lock(server_id="server-b")
    assert first_a.path == second_a.path
    assert first_a.path != lock_b.path


def test_jsonl_mutation_lock_fails_fast_when_another_controller_owns_server(tmp_path: Path) -> None:
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
    first = journal.mutation_lock(server_id="server-a")
    second = journal.mutation_lock(server_id="server-a")
    with first:
        with pytest.raises(ServerMutationBusy, match="server-a"):
            with second:
                pass


def test_jsonl_journal_requires_explicit_resolution_before_new_mutation(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(
        ServerOperationStarted(
            "op-pending",
            "server-a",
            ServerOperationKind.FILE_UPLOAD,
            "b" * 64,
            1.0,
            False,
            _PROFILE_DIGEST,
            ServerOperationEffect.MUTATION,
        )
    )
    journal.record_resolved(
        ServerOperationResolved(
            "op-pending",
            "server-a",
            ServerOperationKind.FILE_UPLOAD,
            "b" * 64,
            ServerOperationResolution.EFFECT_NOT_APPLIED,
            2.0,
            "remote-check:op-pending",
            "c" * 64,
            _PROFILE_DIGEST,
        )
    )
    record = journal.read_operation("op-pending")
    assert record is not None
    assert record.resolution is not None
    assert not record.effect_uncertain
    assert journal.pending_operations() == ()


def test_finished_timeout_remains_effect_uncertain(tmp_path: Path) -> None:
    journal = JsonlServerOperationJournal(tmp_path / "server-operations.jsonl")
    journal.record_started(
        ServerOperationStarted(
            "op-timeout",
            "server-a",
            ServerOperationKind.COMMAND,
            "d" * 64,
            1.0,
            False,
            effect=ServerOperationEffect.MUTATION,
        )
    )
    journal.record_finished(
        ServerOperationFinished(
            "op-timeout",
            "server-a",
            ServerOperationKind.COMMAND,
            "d" * 64,
            ServerOperationState.TIMED_OUT,
            2.0,
            1.0,
            124,
            "timeout",
            0,
            0,
            effect=ServerOperationEffect.MUTATION,
        )
    )
    assert [record.operation_id for record in journal.pending_operations()] == ["op-timeout"]


def test_jsonl_journal_fails_closed_on_corrupt_tail(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    path.write_text('{"event":"started"}\nnot-json\n', encoding="utf-8")
    journal = JsonlServerOperationJournal(path)
    try:
        journal.pending_operations()
    except ServerOperationJournalIntegrityError as exc:
        assert "line" in str(exc)
    else:
        raise AssertionError("corrupt server-operation ledger was accepted")


def _started_mutation(operation_id: str, *, profile: str = _PROFILE_DIGEST) -> ServerOperationStarted:
    return ServerOperationStarted(
        operation_id,
        "server-a",
        ServerOperationKind.FILE_UPLOAD,
        "e" * 64,
        1.0,
        False,
        profile,
        ServerOperationEffect.MUTATION,
    )


def _finished_mutation(operation_id: str, *, profile: str = _PROFILE_DIGEST) -> ServerOperationFinished:
    return ServerOperationFinished(
        operation_id,
        "server-a",
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


def test_journal_rejects_duplicate_finish_before_poisoning_ledger(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-duplicate-finish"))
    finished = _finished_mutation("op-duplicate-finish")
    journal.record_finished(finished)

    with pytest.raises(ServerOperationTransitionConflict, match="already finished"):
        journal.record_finished(finished)

    assert len(path.read_text("utf-8").splitlines()) == 2
    record = journal.read_operation("op-duplicate-finish")
    assert record is not None and record.finished == finished


def test_journal_rejects_profile_drift_before_finish_append(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-profile"))

    with pytest.raises(ServerOperationTransitionConflict, match="identity"):
        journal.record_finished(_finished_mutation("op-profile", profile=_OTHER_PROFILE_DIGEST))

    assert len(path.read_text("utf-8").splitlines()) == 1
    record = journal.read_operation("op-profile")
    assert record is not None and record.finished is None


def test_journal_rejects_finish_after_resolution_before_append(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    operation_id = "op-resolved-first"
    journal.record_started(_started_mutation(operation_id))
    journal.record_resolved(
        ServerOperationResolved(
            operation_id,
            "server-a",
            ServerOperationKind.FILE_UPLOAD,
            "e" * 64,
            ServerOperationResolution.EFFECT_NOT_APPLIED,
            2.0,
            "remote-check:resolved-first",
            "f" * 64,
            _PROFILE_DIGEST,
        )
    )

    with pytest.raises(ServerOperationTransitionConflict, match="already reconciled"):
        journal.record_finished(_finished_mutation(operation_id))

    assert len(path.read_text("utf-8").splitlines()) == 2
    record = journal.read_operation(operation_id)
    assert record is not None and record.finished is None and record.resolution is not None


def test_journal_same_operation_transition_race_is_typed_and_non_corrupting(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    operation_id = "op-resolution-race"
    journal.record_started(_started_mutation(operation_id))
    entered = Event()
    release = Event()
    original_read = journal.read_operation

    def slow_read(candidate: str):
        entered.set()
        assert release.wait(timeout=3)
        return original_read(candidate)

    journal.read_operation = slow_read  # type: ignore[method-assign]
    errors: list[BaseException] = []

    def resolve() -> None:
        try:
            journal.record_resolved(
                ServerOperationResolved(
                    operation_id, "server-a", ServerOperationKind.FILE_UPLOAD,
                    "e" * 64, ServerOperationResolution.EFFECT_NOT_APPLIED,
                    2.0, "remote-check:race", "f" * 64, _PROFILE_DIGEST,
                )
            )
        except BaseException as exc:
            errors.append(exc)
    first = Thread(target=resolve)
    first.start()
    assert entered.wait(timeout=3)
    with pytest.raises(ServerOperationTransitionConflict, match="transition is in progress"):
        journal.record_resolved(
            ServerOperationResolved(
                operation_id, "server-a", ServerOperationKind.FILE_UPLOAD,
                "e" * 64, ServerOperationResolution.EFFECT_NOT_APPLIED,
                3.0, "remote-check:other", "a" * 64, _PROFILE_DIGEST,
            )
        )
    release.set()
    first.join(timeout=3)
    assert not first.is_alive()
    assert errors == []

    journal.read_operation = original_read  # type: ignore[method-assign]
    assert len(path.read_text("utf-8").splitlines()) == 2
    record = journal.read_operation(operation_id)
    assert record is not None and record.resolution is not None
    assert journal.pending_operations() == ()


def test_server_operation_journal_records_form_a_checksum_chain(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-chain"))
    journal.record_finished(_finished_mutation("op-chain"))

    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert rows[0]["journal_schema"] == "server-operation-journal.v2"
    assert rows[0]["previous_checksum"] == "0" * 64
    assert len(rows[0]["record_checksum"]) == 64
    assert rows[1]["previous_checksum"] == rows[0]["record_checksum"]
    assert len(rows[1]["record_checksum"]) == 64


def test_server_operation_journal_rejects_valid_json_payload_tampering(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-tamper"))
    journal.record_finished(_finished_mutation("op-tamper"))
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    rows[0]["server_id"] = "forged-server"
    rows[1]["server_id"] = "forged-server"
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ServerOperationJournalIntegrityError, match="line 1"):
        journal.pending_operations()


def test_server_operation_journal_rejects_missing_chain_prefix(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-prefix"))
    journal.record_finished(_finished_mutation("op-prefix"))
    rows = path.read_text("utf-8").splitlines()
    path.write_text(rows[1] + "\n", encoding="utf-8")

    with pytest.raises(ServerOperationJournalIntegrityError, match="line 1"):
        journal.recent_operations()


def test_server_operation_journal_rejects_legacy_unchecksummed_record(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    path.write_text(
        json.dumps({"event": "started", "operation_id": "legacy"}) + "\n",
        encoding="utf-8",
    )
    journal = JsonlServerOperationJournal(path)
    with pytest.raises(ServerOperationJournalIntegrityError, match="line 1"):
        journal.pending_operations()

def test_server_operation_journal_rejects_typed_field_drift_before_write(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    invalid = ServerOperationStarted(
        "op-type-drift",
        "server-a",
        ServerOperationKind.COMMAND,
        "d" * 64,
        1.0,
        "false",  # type: ignore[arg-type]
        _PROFILE_DIGEST,
        ServerOperationEffect.MUTATION,
    )
    with pytest.raises(ServerOperationJournalIntegrityError, match="started record"):
        journal.record_started(invalid)
    assert not path.exists()


def test_server_operation_journal_fsyncs_parent_only_on_first_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "server-operations.jsonl"
    calls: list[Path] = []
    monkeypatch.setattr(
        "noetrium_platform.infrastructure.lifecycle.server.runtime.operation_journal.fsync_directory",
        lambda candidate: calls.append(candidate),
    )
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-directory-fsync"))
    journal.record_finished(_finished_mutation("op-directory-fsync"))
    assert calls == [tmp_path]


def test_server_operation_journal_refuses_append_after_partial_tail(tmp_path: Path) -> None:
    path = tmp_path / "server-operations.jsonl"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation("op-partial"))
    with path.open("ab") as stream:
        stream.write(b'{"journal_schema":"server-operation-journal.v2"')

    with pytest.raises(ServerOperationJournalIntegrityError, match="line 2") as captured:
        journal.record_started(_started_mutation("op-after-partial"))
    assert captured.value.__cause__ is not None
    assert "partial durable tail" in str(captured.value.__cause__)
    assert b"op-after-partial" not in path.read_bytes()


@pytest.mark.parametrize(
    "field,value",
    (
        ("server_id", "unsafe server"),
        ("request_digest", "not-a-digest"),
        ("profile_digest", "not-a-digest"),
    ),
)
def test_server_operation_journal_rejects_invalid_durable_identity_before_write(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / "server-operations.jsonl"
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
    journal = JsonlServerOperationJournal(path)
    with pytest.raises(ServerOperationJournalIntegrityError, match="started record"):
        journal.record_started(event)
    assert not path.exists()


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
def test_server_operation_journal_rejects_impossible_finished_evidence(
    tmp_path: Path,
    state: ServerOperationState,
    return_code: int,
    failure_kind: str,
    error_type: str | None,
    error_digest: str | None,
) -> None:
    path = tmp_path / "server-operations.jsonl"
    operation_id = "op-invalid-finish"
    journal = JsonlServerOperationJournal(path)
    journal.record_started(_started_mutation(operation_id))
    event = ServerOperationFinished(
        operation_id, "server-a", ServerOperationKind.FILE_UPLOAD, "e" * 64,
        state, 2.0, 1.0, return_code, failure_kind, 0, 0,
        error_type, error_digest, profile_digest=_PROFILE_DIGEST,
        effect=ServerOperationEffect.MUTATION,
    )
    with pytest.raises(ServerOperationJournalIntegrityError, match="finished record"):
        journal.record_finished(event)
    assert len(path.read_text("utf-8").splitlines()) == 1
