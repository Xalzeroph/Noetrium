import math

from noetrium_platform.research.execution.command.api import ExecutionCommand


def test_command_digest_is_canonicalized_and_identity_is_immutable():
    command = ExecutionCommand.create(
        command_id="cmd-1",
        command_type="environment.action",
        payload_schema="action.v1",
        payload_digest="A" * 64,
        deduplication_key="request-1",
        now_unix=10.0,
        deadline_unix=20.0,
    )
    assert command.payload_digest == "a" * 64
    assert command.command_id.value == "cmd-1"
    assert command.deduplication_key is not None
    assert command.deduplication_key.value == "request-1"


def test_command_rejects_non_finite_time():
    for value in (math.inf, -math.inf, math.nan):
        try:
            ExecutionCommand.create(
                command_id="cmd",
                command_type="x",
                payload_schema="x.v1",
                payload_digest="b" * 64,
                now_unix=value,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("non-finite command time must fail closed")


def test_command_identity_does_not_coerce_non_text_values():
    try:
        ExecutionCommand.create(
            command_id=123,  # type: ignore[arg-type]
            command_type="x",
            payload_schema="x.v1",
            payload_digest="c" * 64,
            now_unix=1.0,
        )
    except TypeError:
        pass
    else:
        raise AssertionError("non-text command identity must fail closed")


def test_command_payload_and_timestamps_do_not_coerce_invalid_types():
    for kwargs in (
        {"payload_digest": 123, "now_unix": 1.0},
        {"payload_digest": "d" * 64, "now_unix": True},
        {"payload_digest": "d" * 64, "now_unix": 1.0, "deadline_unix": True},
    ):
        try:
            ExecutionCommand.create(
                command_id="cmd-strict",
                command_type="x",
                payload_schema="x.v1",
                **kwargs,  # type: ignore[arg-type]
            )
        except TypeError:
            pass
        else:
            raise AssertionError("command durable fields must reject implicit coercion")


def test_command_value_object_fields_must_use_typed_wrappers():
    try:
        ExecutionCommand("cmd", "x", "x.v1", "e" * 64, 1.0)  # type: ignore[arg-type]
    except TypeError:
        pass
    else:
        raise AssertionError("ExecutionCommand.command_id must remain a CommandId")
