from __future__ import annotations

import os
from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.capture_paths import (
    ServiceCapturePaths,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.linux_backend import (
    LinuxProcessBackend,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.linux_start_marker import (
    decode_linux_start_handle,
    prepare_linux_start_handle,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.prepared_start import (
    PreparedServiceStartStatus,
)


def _contract(
    root: Path,
    environment: MaterializedServiceEnvironment,
) -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id="model:prepared-visibility",
        generation="g1",
        executable="/bin/true",
        argv=("/bin/true",),
        cwd=str(root),
        environment_digest=environment.digest,
        artifact_digest="a" * 64,
        runtime_identity_digest="b" * 64,
        readiness_timeout_s=5.0,
        stop_timeout_s=5.0,
        heartbeat_interval_s=1.0,
    )


def _captures(root: Path) -> ServiceCapturePaths:
    return ServiceCapturePaths(
        root / "stdout.log",
        root / "stderr.log",
        "capture:stdout",
        "capture:stderr",
    )


class _UnreadableSameUidProcfs:
    def process_ids(self) -> tuple[int, ...]:
        return (7001,)

    def effective_uid(self, pid: int) -> int:
        assert pid == 7001
        return os.geteuid()

    def environment(self, pid: int):
        assert pid == 7001
        raise PermissionError("simulated transient same-UID environ denial")


class _UnreadableOtherUidProcfs(_UnreadableSameUidProcfs):
    def effective_uid(self, pid: int) -> int:
        assert pid == 7001
        return os.geteuid() + 1


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid"),
    reason="Linux prepared-start UID ownership proof",
)
def test_same_uid_unobservable_process_fails_closed_as_unknown(
    tmp_path: Path,
) -> None:
    environment = MaterializedServiceEnvironment.from_mapping(
        {"TEST": "1"},
        "environment:test",
    )
    contract = _contract(tmp_path, environment)
    handle = prepare_linux_start_handle(
        contract,
        environment,
        intent_id="intent-1",
        attempt=1,
    )
    backend = LinuxProcessBackend(
        object(),
        procfs=_UnreadableSameUidProcfs(),  # type: ignore[arg-type]
    )

    result = backend.reconcile_prepared_start(
        contract,
        environment,
        _captures(tmp_path),
        handle,
    )

    assert result.status is PreparedServiceStartStatus.UNKNOWN
    assert result.process is None
    assert result.reason is not None
    assert "same-UID Linux process facts" in result.reason
    assert "7001" in result.reason


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid"),
    reason="Linux prepared-start UID ownership proof",
)
def test_unobservable_other_uid_process_does_not_block_not_started_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.infrastructure.lifecycle.service.runtime.linux_backend as backend_module

    environment = MaterializedServiceEnvironment.from_mapping(
        {"TEST": "1"},
        "environment:test",
    )
    contract = _contract(tmp_path, environment)
    handle = prepare_linux_start_handle(
        contract,
        environment,
        intent_id="intent-2",
        attempt=1,
    )
    token = decode_linux_start_handle(handle, contract, environment)
    monkeypatch.setattr(
        backend_module,
        "time",
        lambda: token.prepared_at_epoch_s + 10.0,
    )
    backend = LinuxProcessBackend(
        object(),
        procfs=_UnreadableOtherUidProcfs(),  # type: ignore[arg-type]
    )

    result = backend.reconcile_prepared_start(
        contract,
        environment,
        _captures(tmp_path),
        handle,
    )

    assert result.status is PreparedServiceStartStatus.NOT_STARTED
    assert result.process is None
