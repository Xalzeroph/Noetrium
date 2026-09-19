from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.environment.api import (
    ActionRequest,
    EnvironmentSession,
    action_request_digest,
    require_action_result_identity,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .environment_fork import EnvironmentSessionOpener


class EnvironmentReplayError(RuntimeError):
    """A fresh-session prefix replay could not be proven accepted in order."""


@dataclass(frozen=True, slots=True)
class EnvironmentReplayReceipt:
    """Composition receipt for a reset/fresh-open plus ordered action-prefix replay.

    This receipt proves only that a fresh provider session associated by the caller
    with source_cut_id accepted the declared ActionRequests in order. It does not
    claim hidden-state equivalence with another session, checkpoint durability,
    exactly-once execution, or crash-recoverable replay.
    """

    session_id: str
    branch_id: str
    source_cut_id: str
    task_id: str
    action_request_digests: tuple[str, ...]
    accepted_action_ids: tuple[str, ...]
    observation_ids: tuple[str | None, ...]
    prefix_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("session_id", self.session_id),
            ("branch_id", self.branch_id),
            ("source_cut_id", self.source_cut_id),
            ("task_id", self.task_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"environment replay {name} is required")
        if type(self.action_request_digests) is not tuple:
            raise TypeError("environment replay action_request_digests must be a tuple")
        if any(type(value) is not str or len(value) != 64 for value in self.action_request_digests):
            raise ValueError("environment replay request digests must be sha256 values")
        if type(self.accepted_action_ids) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.accepted_action_ids
        ):
            raise TypeError("environment replay accepted_action_ids must contain non-empty strings")
        if type(self.observation_ids) is not tuple or any(
            value is not None and (type(value) is not str or not value.strip())
            for value in self.observation_ids
        ):
            raise TypeError("environment replay observation_ids must contain strings or None")
        if not (
            len(self.action_request_digests)
            == len(self.accepted_action_ids)
            == len(self.observation_ids)
        ):
            raise ValueError("environment replay receipt vectors must have equal length")
        expected = canonical_digest(
            {
                "source_cut_id": self.source_cut_id,
                "task_id": self.task_id,
                "action_request_digests": self.action_request_digests,
            }
        )
        if self.prefix_digest != expected:
            raise ValueError("environment replay prefix digest does not match its declared prefix")


def replay_environment_prefix(
    *,
    session_id: str,
    branch_id: str,
    source_cut_id: str,
    task_id: str,
    requests: tuple[ActionRequest, ...],
    open_fresh: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentReplayReceipt]:
    """Open a fresh source-bound session and replay one explicit action prefix.

    open_fresh is provider/composition owned and must open the task at its frozen
    initial cut. Requests are supplied explicitly for the new session; this helper
    never clones action ids or mutates tracing/semantic identity.

    The helper intentionally does not compare private provider state with any
    source session. Providers that support truthful checkpoints should use
    fork_environment_session instead when exact snapshot restoration is required.
    """

    for name, value in (
        ("session_id", session_id),
        ("branch_id", branch_id),
        ("source_cut_id", source_cut_id),
        ("task_id", task_id),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"environment replay {name} is required")
    if type(requests) is not tuple or any(not isinstance(row, ActionRequest) for row in requests):
        raise TypeError("environment replay requests must be a tuple of ActionRequest")
    if not callable(open_fresh):
        raise TypeError("environment replay requires a fresh-session opener")

    child = open_fresh(session_id)
    if not isinstance(child, EnvironmentSession):
        raise TypeError("environment replay opener must return EnvironmentSession")

    request_digests: list[str] = []
    accepted_ids: list[str] = []
    observation_ids: list[str | None] = []
    try:
        for index, request in enumerate(requests):
            if request.context.task_id is not None and request.context.task_id != task_id:
                raise EnvironmentReplayError(
                    f"environment replay request {index} task identity mismatch: "
                    f"expected={task_id} actual={request.context.task_id}"
                )
            result = require_action_result_identity(
                request,
                child.act(request),
                source=f"environment replay action[{index}]",
            )
            if not result.accepted:
                raise EnvironmentReplayError(
                    f"environment replay action[{index}] was rejected: {request.action_id}"
                )
            request_digests.append(action_request_digest(request))
            accepted_ids.append(result.action_id)
            observation_ids.append(
                None if result.observation is None else result.observation.observation_id
            )
    except BaseException:
        child.close()
        raise

    digests = tuple(request_digests)
    receipt = EnvironmentReplayReceipt(
        session_id=session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        task_id=task_id,
        action_request_digests=digests,
        accepted_action_ids=tuple(accepted_ids),
        observation_ids=tuple(observation_ids),
        prefix_digest=canonical_digest(
            {
                "source_cut_id": source_cut_id,
                "task_id": task_id,
                "action_request_digests": digests,
            }
        ),
    )
    return child, receipt


__all__ = [
    "EnvironmentReplayError",
    "EnvironmentReplayReceipt",
    "replay_environment_prefix",
]
