from __future__ import annotations

from noetrium_platform.product.research_control import ResearchControlAction, ResearchControlReceipt, ResearchExecutionTarget, ResearchGraphRevision

from dataclasses import dataclass

import pytest

from noetrium_platform.composition.operator.project import project_research_loader as loader
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessLockBusy


def _revision(seed: str) -> ResearchGraphRevision:
    return ResearchGraphRevision("paper", seed * 64)


@dataclass
class _Owner:
    active_revision: ResearchGraphRevision | None

    def ensure_execution_plane(self) -> None:
        raise InterprocessLockBusy("owned by live process")


class _Delegate:
    def __init__(self, *, live: bool = True) -> None:
        self.live = live
        self.inspected = []

    def inspect(self, target, payload=None):
        assert payload is None
        self.inspected.append(target)
        states = {
            "claimed": ("paper::root",) if self.live else (),
            "running": (),
        }
        row = {"states": states, "control_phase": "active"}
        return ResearchControlReceipt(
            ResearchControlAction.INSPECT,
            target,
            "durable",
            canonical_digest({"inspect": target.target_digest, "states": states}),
            row,
        )


def test_run_attaches_to_same_revision_live_owner_instead_of_exposing_lock_busy():
    revision = _revision("a")
    delegate = _Delegate(live=True)
    owner = _Owner(revision)
    target = ResearchExecutionTarget("paper", revision)

    receipt = loader._run_bound_control(owner, delegate, target)

    assert receipt.action is ResearchControlAction.RUN
    assert receipt.state == "already_running"
    assert receipt.target == target
    assert receipt.payload["attached_to_existing_owner"] is True
    assert receipt.payload["owner_fence"] == "managed-research-runtime"
    assert delegate.inspected == [target]


def test_run_does_not_hide_lock_when_working_revision_differs():
    active = _revision("a")
    working = _revision("b")
    owner = _Owner(active)
    delegate = _Delegate(live=True)

    with pytest.raises(InterprocessLockBusy):
        loader._run_bound_control(owner, delegate, ResearchExecutionTarget("paper", working))


def test_run_does_not_hide_lock_when_owner_has_no_live_graph_work():
    revision = _revision("a")
    owner = _Owner(revision)
    delegate = _Delegate(live=False)

    with pytest.raises(InterprocessLockBusy):
        loader._run_bound_control(owner, delegate, ResearchExecutionTarget("paper", revision))
