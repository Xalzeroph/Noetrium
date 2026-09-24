from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import JsonInput


def environment_action_capability_payload(
    action_type: str,
    payload: JsonInput,
) -> dict[str, JsonInput]:
    """Build the MethodProgram envelope for one Environment action capability."""
    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("environment capability action_type must be non-empty")
    return {"action_type": action_type, "payload": payload}


def environment_query_capability_payload(
    query_type: str,
    payload: JsonInput,
) -> dict[str, JsonInput]:
    """Build the MethodProgram envelope for one Environment query capability."""
    if not isinstance(query_type, str) or not query_type.strip():
        raise ValueError("environment query capability query_type must be non-empty")
    return {"query_type": query_type, "payload": payload}


def environment_reset_capability_payload(
    metadata: Mapping[str, JsonInput] | None = None,
) -> dict[str, JsonInput]:
    """Build the MethodProgram envelope for one Environment reset capability."""
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise TypeError("environment reset metadata must be a mapping")
    return {str(key): value for key, value in metadata.items()}


def environment_branch_action_spec(
    action_type: str,
    payload: JsonInput,
) -> dict[str, JsonInput]:
    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("environment branch action_type must be non-empty")
    return {"action_type": action_type, "payload": payload}


def environment_fork_action_payload(
    *,
    parent_branch_id: str,
    child_branch_id: str,
    source_cut_id: str,
    action_type: str,
    action_payload: JsonInput,
) -> dict[str, JsonInput]:
    for name, value in (
        ("parent_branch_id", parent_branch_id),
        ("child_branch_id", child_branch_id),
        ("source_cut_id", source_cut_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"environment fork payload {name} must be non-empty")
    return {
        "operation": "fork_action",
        "parent_branch_id": parent_branch_id,
        "child_branch_id": child_branch_id,
        "source_cut_id": source_cut_id,
        "action": environment_branch_action_spec(action_type, action_payload),
    }


def environment_replay_action_payload(
    *,
    branch_id: str,
    source_cut_id: str,
    committed_actions: Sequence[Mapping[str, JsonInput]],
    action_type: str,
    action_payload: JsonInput,
    retain_branch: bool = False,
) -> dict[str, JsonInput]:
    for name, value in (("branch_id", branch_id), ("source_cut_id", source_cut_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"environment replay payload {name} must be non-empty")
    if not isinstance(committed_actions, Sequence) or isinstance(
        committed_actions, (str, bytes, bytearray)
    ):
        raise TypeError("environment replay committed_actions must be a sequence")
    actions = []
    for row in committed_actions:
        if not isinstance(row, Mapping):
            raise TypeError("environment replay committed action must be a mapping")
        action_kind = row.get("action_type")
        if not isinstance(action_kind, str) or not action_kind.strip():
            raise ValueError("environment replay committed action requires action_type")
        if "payload" not in row:
            raise ValueError("environment replay committed action requires payload")
        actions.append(environment_branch_action_spec(action_kind, row["payload"]))
    if type(retain_branch) is not bool:
        raise TypeError("environment replay retain_branch must be boolean")
    return {
        "operation": "replay_action",
        "branch_id": branch_id,
        "source_cut_id": source_cut_id,
        "committed_actions": tuple(actions),
        "action": environment_branch_action_spec(action_type, action_payload),
        "retain_branch": retain_branch,
    }


__all__ = [
    "environment_action_capability_payload",
    "environment_branch_action_spec",
    "environment_fork_action_payload",
    "environment_query_capability_payload",
    "environment_replay_action_payload",
    "environment_reset_capability_payload",
]
