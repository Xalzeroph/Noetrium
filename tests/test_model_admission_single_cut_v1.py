"""One authoritative observation cut covers model slots and continuity borrows."""
from __future__ import annotations

from model_admission_test_support import make_model_admission_controller


class _CountingAuthority:
    def __init__(self, delegate):
        self._delegate = delegate
        self.cuts = []

    def snapshot_for_resource_keys(self, keys):
        self.cuts.append(keys)
        return self._delegate.snapshot_for_resource_keys(keys)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def test_mixed_model_claim_snapshot_and_close_share_one_authority_cut() -> None:
    controller = make_model_admission_controller(2)
    controller.qualify_continuity(1)
    observer = _CountingAuthority(controller._authority)
    controller._authority = observer

    ordinary = controller.acquire(owner_id="ordinary")
    reserved = controller.try_reserve_continuity(owner_id="continuity", flow_id="flow")
    assert reserved is not None
    borrowed = controller.acquire(
        owner_id="continuity", continuity_claim_id=reserved.claim_id
    )
    observer.cuts.clear()
    observed = controller.snapshot()
    assert len(observer.cuts) == 1
    assert observer.cuts[0] == frozenset({
        controller._resource_key, controller._continuity_resource_key,
    })
    assert observed.active == 2
    assert {row.owner_id: row.active for row in observed.owners} == {
        "continuity": 1, "ordinary": 1,
    }

    borrowed.release()
    reserved.release()
    ordinary.release()
    observer.cuts.clear()
    controller.close()
    assert controller.closed
    assert len(observer.cuts) == 1
    assert controller._test_registry.close() is None
