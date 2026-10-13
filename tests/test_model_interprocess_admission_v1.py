from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionTimeout
from noetrium_platform.capabilities.model.serving.runtime import (
    ModelAdmissionRegistry,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)


_GENERATION = "a" * 64


def _registry(
    root: Path,
    *,
    ttl_seconds: float = 5.0,
) -> tuple[UniversalResourceAuthority, object, ModelAdmissionRegistry]:
    authority = UniversalResourceAuthority(root / "authority.sqlite")
    owner = uuid4().hex
    lease = authority.acquire_ttl_lease(
        lease_id="model-admission-test-owner:" + owner,
        resource_key="model-admission-test-owner:" + owner,
        holder_key="model-admission-test-owner:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=ttl_seconds,
        metadata={"kind": "model-admission-test-owner"},
    )
    return authority, lease, ModelAdmissionRegistry(authority, lease)


def test_interprocess_model_admission_enforces_one_host_wide_ceiling(
    tmp_path: Path,
) -> None:
    root = tmp_path / "model-admission"
    root.mkdir()
    script = r'''
import sys, time
from pathlib import Path
from uuid import uuid4
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority

root = Path(sys.argv[1])
authority = UniversalResourceAuthority(root / "authority.sqlite")
owner = uuid4().hex
owner_lease = authority.acquire_ttl_lease(
    lease_id="model-admission-child:" + owner,
    resource_key="model-admission-child:" + owner,
    holder_key="model-admission-child:" + owner,
    owner_scope=PLATFORM_SCOPE,
    ttl_seconds=5.0,
    metadata={"kind": "model-admission-test-owner"},
)
registry = ModelAdmissionRegistry(authority, owner_lease)
controller = registry.controller_for(
    deployment_id="model",
    deployment_generation="a"*64,
    qualified_capacity=1,
)
lease = controller.acquire(timeout_seconds=1.0, owner_id="child")
print("READY", flush=True)
time.sleep(0.6)
lease.release()
registry.close()
authority.release_lease(owner_lease)
authority.close()
'''
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    authority = owner_lease = registry = None
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "READY"
        authority, owner_lease, registry = _registry(root)
        controller = registry.controller_for(
            deployment_id="model",
            deployment_generation=_GENERATION,
            qualified_capacity=1,
        )
        with pytest.raises(ModelAdmissionTimeout):
            controller.acquire(timeout_seconds=0.1, owner_id="parent")
        assert child.wait(timeout=3.0) == 0
        with controller.acquire(timeout_seconds=0.5, owner_id="parent"):
            pass
        registry.close()
        authority.release_lease(owner_lease)
        authority.close()
        registry = None
        authority = None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3.0)
        if registry is not None:
            registry.close()
        if authority is not None:
            if owner_lease is not None:
                authority.release_lease(owner_lease)
            authority.close()


def test_model_admission_rejects_capacity_drift(tmp_path: Path) -> None:
    root = tmp_path / "model-admission"
    root.mkdir()
    authority_a, lease_a, first = _registry(root)
    authority_b, lease_b, second = _registry(root)
    try:
        first.controller_for(
            deployment_id="model",
            deployment_generation=_GENERATION,
            qualified_capacity=2,
        )
        with pytest.raises(ValueError, match="capacity drift"):
            second.controller_for(
                deployment_id="model",
                deployment_generation=_GENERATION,
                qualified_capacity=3,
            )
    finally:
        first.close()
        second.close()
        authority_a.release_lease(lease_a)
        authority_b.release_lease(lease_b)
        authority_a.close()
        authority_b.close()


def test_expired_owner_claim_is_recovered_by_next_admission(tmp_path: Path) -> None:
    root = tmp_path / "model-admission"
    root.mkdir()
    script = r'''
import sys
from pathlib import Path
from uuid import uuid4
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority

root = Path(sys.argv[1])
authority = UniversalResourceAuthority(root / "authority.sqlite")
owner = uuid4().hex
owner_lease = authority.acquire_ttl_lease(
    lease_id="model-admission-crash:" + owner,
    resource_key="model-admission-crash:" + owner,
    holder_key="model-admission-crash:" + owner,
    owner_scope=PLATFORM_SCOPE,
    ttl_seconds=0.20,
    metadata={"kind": "model-admission-test-owner"},
)
registry = ModelAdmissionRegistry(authority, owner_lease)
controller = registry.controller_for(
    deployment_id="model",
    deployment_generation="a"*64,
    qualified_capacity=1,
)
controller.acquire(timeout_seconds=1.0, owner_id="crashed-owner")
print("READY", flush=True)
# Deliberately exit without release/registry close/lease release.
'''
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "READY"
    assert child.wait(timeout=3.0) == 0

    time.sleep(0.30)
    authority, owner_lease, registry = _registry(root)
    try:
        controller = registry.controller_for(
            deployment_id="model",
            deployment_generation=_GENERATION,
            qualified_capacity=1,
        )
        with controller.acquire(
            timeout_seconds=0.5,
            owner_id="replacement-owner",
        ):
            assert controller.snapshot().active == 1
        assert controller.snapshot().active == 0
    finally:
        registry.close()
        authority.release_lease(owner_lease)
        authority.close()


def test_controller_close_wakes_cross_owner_waiter_without_polling(tmp_path: Path) -> None:
    from threading import Thread
    from noetrium_platform.capabilities.model.serving.api import ModelAdmissionClosed

    root = tmp_path / "model-close"
    root.mkdir()
    authority_a, lease_a, registry_a = _registry(root)
    authority_b, lease_b, registry_b = _registry(root)
    blocking = None
    try:
        controller_a = registry_a.controller_for(
            deployment_id="model", deployment_generation=_GENERATION, qualified_capacity=1,
        )
        controller_b = registry_b.controller_for(
            deployment_id="model", deployment_generation=_GENERATION, qualified_capacity=1,
        )
        blocking = controller_a.acquire(owner_id="first-owner")
        controller_b._CROSS_PROCESS_RECHECK_SECONDS = 30.0
        errors: list[BaseException] = []

        def contender() -> None:
            try:
                controller_b.acquire(timeout_seconds=40, owner_id="second-owner")
            except BaseException as exc:
                errors.append(exc)

        thread = Thread(target=contender, daemon=True)
        thread.start()
        deadline = time.monotonic() + 2
        while controller_b.snapshot().waiting != 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert controller_b.snapshot().waiting == 1
        registry_b.close()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], ModelAdmissionClosed)
    finally:
        if blocking is not None:
            blocking.release()
        registry_a.close()
        registry_b.close()
        authority_a.release_lease(lease_a)
        authority_b.release_lease(lease_b)
        authority_a.close()
        authority_b.close()
