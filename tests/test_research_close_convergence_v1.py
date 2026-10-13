from __future__ import annotations

import pytest

from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime
from noetrium_platform.composition.operator.project.project_research_loader import (
    LoadedResearchRoot,
)


class _Recorder:
    def __init__(self, events: list[str], name: str, *, fail: bool = False) -> None:
        self.events = events
        self.name = name
        self.fail = fail

    def close(self) -> None:
        self.events.append(self.name)
        if self.fail:
            raise RuntimeError(self.name)


class _Authorities:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def retire(self):
        self.events.append("authorities.retire")
        if self.fail:
            raise RuntimeError("authorities.retire")
        return ()


class _LoadedRuntime:
    def __init__(self, events: list[str], *, quiesce_fail: bool = False) -> None:
        self.events = events
        self.quiesce_fail = quiesce_fail

    def quiesce_workloads(self) -> None:
        self.events.append("runtime.quiesce")
        if self.quiesce_fail:
            raise RuntimeError("runtime.quiesce")

    def close(self) -> None:
        self.events.append("runtime.close")


def _loaded_root(
    events: list[str],
    *,
    authorities_fail: bool = False,
) -> LoadedResearchRoot:
    return LoadedResearchRoot(
        project_roots=(),
        state_root=None,  # unused by close
        sources=(_Recorder(events, "source.close"),),
        portfolio=object(),
        revision=object(),
        active_revision=None,
        _control=object(),
        execution_pool=None,
        _composition=_Recorder(events, "composition.close"),
        _managed_runtime=_LoadedRuntime(events),
        _owns_managed_runtime=True,
        _execution_authorities=_Authorities(events, fail=authorities_fail),
    )


def test_loaded_root_retires_execution_lifetimes_before_workload_quiescence() -> None:
    events: list[str] = []
    loaded = _loaded_root(events)

    loaded.close()

    assert events == [
        "authorities.retire",
        "runtime.quiesce",
        "composition.close",
        "runtime.close",
        "source.close",
    ]


def test_loaded_root_continues_all_cleanup_after_retirement_failure() -> None:
    events: list[str] = []
    loaded = _loaded_root(events, authorities_fail=True)

    with pytest.raises(BaseExceptionGroup):
        loaded.close()

    assert events == [
        "authorities.retire",
        "runtime.quiesce",
        "composition.close",
        "runtime.close",
        "source.close",
    ]


class _Pool:
    def __init__(self, events: list[str], *, quiesce_fail: bool = False,
                 close_fail: bool = False) -> None:
        self.events = events
        self.quiesce_fail = quiesce_fail
        self.close_fail = close_fail
        self.control_closed = False

    def quiesce_workloads(self) -> None:
        self.events.append("pool.quiesce")
        if self.quiesce_fail:
            raise RuntimeError("pool.quiesce")

    def close_control_group(self, _group, *, cancel_pending: bool) -> None:
        assert cancel_pending
        self.control_closed = True
        self.events.append("pool.control.close")

    def close_orchestration_group(self, _group, *, cancel_pending: bool) -> None:
        assert cancel_pending
        self.events.append("pool.orchestration.close")

    def close(self) -> None:
        # A physical resource may still need Docker I/O in this call.
        assert not self.control_closed, "Docker I/O closed before physical resources"
        self.events.append("pool.close")
        if self.close_fail:
            raise RuntimeError("physical lifecycle retirement unavailable")


class _Lock:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        self.events.append("lock.release")
        return False


def _managed_runtime(
    events: list[str],
    *,
    quiesce_fail: bool = False,
    pool_close_fail: bool = False,
) -> ManagedResearchRuntime:
    return ManagedResearchRuntime(
        execution_pool=_Pool(events, quiesce_fail=quiesce_fail,
                             close_fail=pool_close_fail),
        management=object(),
        observability=_Recorder(events, "observability.close"),
        operation_runtime=_Recorder(events, "operation.close"),
        recovery_execution=object(),
        services=object(),
        _orchestration_group=object(),
        _docker_group=object(),
        _runtime_lock=_Lock(events),
    )


def test_managed_runtime_continues_independent_close_stages_after_failure() -> None:
    events: list[str] = []
    runtime = _managed_runtime(events, quiesce_fail=True)

    with pytest.raises(BaseExceptionGroup):
        runtime.close()

    assert events == [
        "pool.quiesce",
        "operation.close",
        "observability.close",
        "pool.close",
    ]
    assert "lock.release" not in events


def test_managed_runtime_releases_final_fence_only_after_full_convergence() -> None:
    events: list[str] = []
    runtime = _managed_runtime(events)

    runtime.close()

    assert events == [
        "pool.quiesce",
        "operation.close",
        "observability.close",
        "pool.close",
        "lock.release",
    ]


def test_physical_cleanup_failure_attempts_independent_group_shutdown() -> None:
    events: list[str] = []
    runtime = _managed_runtime(events, pool_close_fail=True)
    with pytest.raises(BaseExceptionGroup) as error:
        runtime.close()
    assert "physical lifecycle retirement unavailable" in str(error.value.exceptions)
    assert events == [
        "pool.quiesce", "operation.close", "observability.close",
        "pool.close", "pool.control.close", "pool.orchestration.close",
    ]
    assert "lock.release" not in events
