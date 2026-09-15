from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.composition.environment_fork import fork_environment_session


class _Session:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False

    def observe(self, context):
        raise AssertionError("fork composition must not observe")

    def act(self, request):
        raise AssertionError("fork composition must not act")

    def reconcile(self, effect, context):
        raise AssertionError("fork composition must not reconcile")

    def checkpoint(self) -> bytes:
        return self.payload

    def restore(self, payload: bytes) -> None:
        self.payload = payload

    def close(self) -> None:
        self.closed = True


def test_environment_fork_restores_opaque_parent_cut_into_distinct_child() -> None:
    parent = _Session(b"provider-owned-state")
    children: list[_Session] = []

    def open_child(session_id: str):
        assert session_id == "session:child"
        child = _Session(b"empty")
        children.append(child)
        return child

    child, receipt = fork_environment_session(
        parent,
        parent_session_id="session:parent",
        child_session_id="session:child",
        branch_id="branch:7",
        source_cut_id="cut:parent:42",
        open_child=open_child,
    )

    assert child is children[0]
    assert child.payload == b"provider-owned-state"
    assert parent.payload == b"provider-owned-state"
    assert receipt.branch_id == "branch:7"
    assert receipt.source_cut_id == "cut:parent:42"
    assert receipt.source_checkpoint_sha256 == hashlib.sha256(b"provider-owned-state").hexdigest()


def test_environment_fork_fails_closed_and_closes_partial_child_on_restore_error() -> None:
    parent = _Session(b"provider-owned-state")

    class Broken(_Session):
        def restore(self, payload: bytes) -> None:
            raise RuntimeError("restore rejected")

    child = Broken(b"empty")
    with pytest.raises(RuntimeError, match="restore rejected"):
        fork_environment_session(
            parent,
            parent_session_id="session:parent",
            child_session_id="session:child",
            branch_id="branch:7",
            source_cut_id="cut:parent:42",
            open_child=lambda _session_id: child,
        )
    assert child.closed


def test_environment_fork_rejects_aliasing_parent_as_child() -> None:
    parent = _Session(b"provider-owned-state")
    with pytest.raises(ValueError, match="returned the parent"):
        fork_environment_session(
            parent,
            parent_session_id="session:parent",
            child_session_id="session:child",
            branch_id="branch:7",
            source_cut_id="cut:parent:42",
            open_child=lambda _session_id: parent,
        )
