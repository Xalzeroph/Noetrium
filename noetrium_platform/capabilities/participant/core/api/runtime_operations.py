from __future__ import annotations

import re


PARTICIPANT_OPERATION_VERBS = frozenset({
    "resolve",
    "open_session",
    "close",
    "checkpoint",
    "restore",
})
_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ParticipantOperationContractError(ValueError):
    pass


def validate_participant_kind(kind: str) -> str:
    if not isinstance(kind, str) or _KIND_PATTERN.fullmatch(kind) is None:
        raise ParticipantOperationContractError(
            f"participant kind must be a stable lowercase operation namespace: {kind!r}"
        )
    return kind


def participant_operation_type(kind: str, verb: str) -> str:
    """Build the runtime lifecycle operation namespace for any participant kind.

    Kinds are extension points. Lifecycle verbs are the frozen runtime ABI.  This
    contract deliberately lives below Study so Forensics, Runtime and arbitrary
    participant implementations can share the lifecycle vocabulary without
    depending on the Study orchestration package.
    """

    validate_participant_kind(kind)
    if verb not in PARTICIPANT_OPERATION_VERBS:
        raise ParticipantOperationContractError(
            f"unsupported participant operation verb: {verb!r}"
        )
    return f"{kind}.{verb}"


def participant_operation_verb(operation_type: str) -> str | None:
    if not isinstance(operation_type, str) or "." not in operation_type:
        return None
    kind, verb = operation_type.rsplit(".", 1)
    try:
        validate_participant_kind(kind)
    except ParticipantOperationContractError:
        return None
    return verb if verb in PARTICIPANT_OPERATION_VERBS else None


__all__ = [
    "PARTICIPANT_OPERATION_VERBS",
    "ParticipantOperationContractError",
    "participant_operation_type",
    "participant_operation_verb",
    "validate_participant_kind",
]
