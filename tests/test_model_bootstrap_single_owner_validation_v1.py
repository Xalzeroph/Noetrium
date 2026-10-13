"""Bootstrap uses the single verified pool.ensure cut without a second O(R) probe."""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from noetrium_platform.composition import model_runtime_bootstrap as bootstrap


def _parameters(monkeypatch, *, physical_error=False):
    monkeypatch.setattr(
        bootstrap, "ModelReplicaPoolRequest",
        lambda **arguments: SimpleNamespace(**arguments),
    )
    placement = SimpleNamespace(
        deployment_id="physical-a", host_id="host-a",
        gpu_ids=("gpu-1",), endpoint_host="127.0.0.1", endpoint_port=45124,
    )
    calls = []

    class Lease:
        report = SimpleNamespace(placements=(placement,))

        def assert_healthy(self):
            raise AssertionError("duplicate model owner liveness verification")

        def close(self):
            calls.append("close")

    lease = Lease()

    class Pool:
        def ensure(self, request):
            calls.append("ensure")
            return lease

    def applied_identity(deployment_id):
        assert deployment_id == "physical-a"
        calls.append("applied_identity")
        if physical_error:
            raise RuntimeError("live applied identity drift")
        return SimpleNamespace(pid=100)

    stack = SimpleNamespace(
        identity=SimpleNamespace(engine="vllm"),
        digest=lambda: "a" * 64,
        tensor_parallel=1,
        identity_digest="b" * 64,
    )
    return dict(
        model_id="model-a",
        roles=("agent",),
        stack=stack,
        compute=object(),
        runtime_workdir=__import__("pathlib").Path("/tmp/qualified-test"),
        model_replica_pool=Pool(),
        deployment_runtime=SimpleNamespace(applied_identity=applied_identity),
    ), calls


def test_ensure_receipt_is_authoritative_no_second_synchronous_probe(monkeypatch):
    kwargs, calls = _parameters(monkeypatch)
    _, lease, placements, identities = bootstrap._realize_model_stack(**kwargs)
    assert len(placements) == len(identities) == 1
    assert identities[0].pid == 100
    assert calls == ["ensure", "applied_identity"]


def test_applied_process_drift_still_fails_closed_and_releases_lease(monkeypatch):
    kwargs, calls = _parameters(monkeypatch, physical_error=True)
    with pytest.raises(RuntimeError, match="identity drift"):
        bootstrap._realize_model_stack(**kwargs)
    assert calls == ["ensure", "applied_identity", "close"]
