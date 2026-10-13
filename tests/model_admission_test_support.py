from __future__ import annotations

from pathlib import Path
import tempfile
from uuid import uuid4

from noetrium_platform.capabilities.model.serving.runtime import (
    ModelAdmissionController,
    ModelAdmissionRegistry,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)


def make_model_admission_registry() -> ModelAdmissionRegistry:
    tempdir = tempfile.TemporaryDirectory(prefix="noetrium-model-admission-test-")
    authority = UniversalResourceAuthority(
        Path(tempdir.name) / "authority.sqlite"
    )
    owner = uuid4().hex
    owner_lease = authority.acquire_ttl_lease(
        lease_id="model-admission-test-owner:" + owner,
        resource_key="model-admission-test-owner:" + owner,
        holder_key="model-admission-test-owner:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=3600.0,
        metadata={"kind": "model-admission-test-owner"},
    )
    registry = ModelAdmissionRegistry(authority, owner_lease)
    registry._test_tempdir = tempdir
    registry._test_authority = authority
    registry._test_owner_lease = owner_lease
    return registry


def make_model_admission_controller(
    qualified_capacity: int,
    *,
    deployment_id: str = "deployment",
    deployment_generation: str = "a" * 64,
) -> ModelAdmissionController:
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id=deployment_id,
        deployment_generation=deployment_generation,
        qualified_capacity=qualified_capacity,
    )
    controller._test_registry = registry
    return controller
