from __future__ import annotations

from threading import RLock
from types import SimpleNamespace
import pytest

from noetrium_platform.capabilities.model.deployment.runtime.deployment_runtime import (
    ModelDeploymentRuntime,
)
from noetrium_platform.infrastructure.lifecycle.service.api.ports import (
    ServiceQuiescenceOutcome,
)


def _runtime(*, physical_quiescent: bool, with_matching: bool=True, active: bool=True):
    target="target-model-retired"
    digest="a"*64
    expected=ServiceQuiescenceOutcome(
        digest if with_matching else "b"*64,
        physical_quiescent,
        "exact Docker physical process absent" if physical_quiescent else
        "exact physical process not confirmed absent",
    )

    class Store:
        def __init__(self):
            self.active=SimpleNamespace(
                contract=SimpleNamespace(digest=lambda:digest),
                runtime_digest="c"*64,
            ) if active else None
            self.events=[]

        def read(self, deployment_id):
            assert deployment_id==target
            self.events.append("read")
            return self.active

        def clear(self, deployment_id, *,expected_runtime_digest):
            assert deployment_id==target and expected_runtime_digest=="c"*64
            assert self.active is not None
            self.events.append("clear")
            self.active=None
            return True

        def purge_cleared_after_retirement(self, deployment_id):
            assert deployment_id==target
            assert self.active is None, "cannot purge active generation"
            self.events.append("purge")
            return 1

    store=Store()
    instance=object.__new__(ModelDeploymentRuntime)
    instance._lock=RLock()
    instance._catalog=SimpleNamespace(retired_deployment_ids=lambda:(target,))
    instance._service_factory=SimpleNamespace(quiesce_retired=lambda deployment_id:(expected,))
    instance._applied_store=store
    return instance,store,expected


def test_exact_quiescence_closes_crash_window_before_retired_projection_purge():
    runtime,store,receipt=_runtime(physical_quiescent=True)
    assert runtime.reconcile_retired_orphans()==(receipt,)
    assert store.events==["read","clear","purge"]
    assert store.active is None
    # Rerun is idempotent: no applied generation to clear, no double teardown.
    assert runtime.reconcile_retired_orphans()==(receipt,)
    assert store.events==["read","clear","purge","read","purge"]


@pytest.mark.parametrize("quiescent,matching",[
    (False,True),
    (True,False),
])
def test_retirement_refuses_to_clear_unproven_or_mismatched_generation(quiescent,matching):
    runtime,store,_=_runtime(physical_quiescent=quiescent,with_matching=matching)
    with pytest.raises(RuntimeError,match="lacks exact physical quiescence evidence"):
        runtime.reconcile_retired_orphans()
    assert store.events==["read"]
    assert store.active is not None


def test_already_cleared_retired_generation_purges_without_fake_physical_repair():
    runtime,store,receipt=_runtime(physical_quiescent=True,active=False)
    assert runtime.reconcile_retired_orphans()==(receipt,)
    assert store.events==["read","purge"]
