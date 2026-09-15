from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from noetrium_platform.capabilities.environment.api import EnvironmentSession


@dataclass(frozen=True, slots=True)
class EnvironmentForkReceipt:
    """Composition receipt for one environment branch restoration.

    This receipt proves which opaque parent checkpoint was used to initialize a
    distinct child session. It is not an environment state store and does not
    claim task success or state equivalence beyond the provider accepting the
    restore operation.
    """

    parent_session_id: str
    child_session_id: str
    branch_id: str
    source_cut_id: str
    source_checkpoint_sha256: str

    def __post_init__(self) -> None:
        for name, value in (
            ("parent_session_id", self.parent_session_id),
            ("child_session_id", self.child_session_id),
            ("branch_id", self.branch_id),
            ("source_cut_id", self.source_cut_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"environment fork {name} is required")
        if self.parent_session_id == self.child_session_id:
            raise ValueError("environment fork child session must be distinct from parent")
        if len(self.source_checkpoint_sha256) != 64:
            raise ValueError("environment fork source checkpoint digest must be sha256")


EnvironmentSessionOpener = Callable[[str], EnvironmentSession]


def fork_environment_session(
    parent: EnvironmentSession,
    *,
    parent_session_id: str,
    child_session_id: str,
    branch_id: str,
    source_cut_id: str,
    open_child: EnvironmentSessionOpener,
) -> tuple[EnvironmentSession, EnvironmentForkReceipt]:
    """Restore one child session from the parent's provider-owned checkpoint.

    The helper deliberately owns no persistence and no provider-specific state.
    Parent checkpoint bytes remain opaque; only their digest crosses the
    composition seam. If restore fails, the partially opened child is closed
    before the error is propagated.
    """

    if not isinstance(parent, EnvironmentSession):
        raise TypeError("environment fork requires EnvironmentSession parent")
    if not callable(open_child):
        raise TypeError("environment fork requires a child-session opener")
    for name, value in (
        ("parent_session_id", parent_session_id),
        ("child_session_id", child_session_id),
        ("branch_id", branch_id),
        ("source_cut_id", source_cut_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"environment fork {name} is required")
    if parent_session_id == child_session_id:
        raise ValueError("environment fork child session must be distinct from parent")

    checkpoint = parent.checkpoint()
    if not isinstance(checkpoint, bytes) or not checkpoint:
        raise ValueError("environment parent checkpoint must be non-empty bytes")
    checkpoint_digest = sha256(checkpoint).hexdigest()

    child = open_child(child_session_id)
    if not isinstance(child, EnvironmentSession):
        raise TypeError("environment child opener must return EnvironmentSession")
    if child is parent:
        raise ValueError("environment fork opener returned the parent session")
    try:
        child.restore(checkpoint)
    except BaseException:
        try:
            child.close()
        finally:
            raise

    return child, EnvironmentForkReceipt(
        parent_session_id=parent_session_id,
        child_session_id=child_session_id,
        branch_id=branch_id,
        source_cut_id=source_cut_id,
        source_checkpoint_sha256=checkpoint_digest,
    )


__all__ = ["EnvironmentForkReceipt", "EnvironmentSessionOpener", "fork_environment_session"]
