from __future__ import annotations

import pytest

from noetrium_platform.infrastructure.lifecycle.runtime import (
    ResourceLifetimeController,
    ResourceLifetimePhase,
)
from noetrium_platform.infrastructure.resources.authority.runtime.authority import (
    UniversalResourceAuthority,
)


def _controller(tmp_path):
    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    controller = ResourceLifetimeController(
        "research-execution:test",
        "owner-generation:test",
        authority,
    )
    return authority, controller


def test_resource_lifetime_blocks_retirement_while_borrowed_and_retires_reverse_dependencies(tmp_path):
    closed: list[str] = []
    authority, controller = _controller(tmp_path)
    controller.register("content", retire=lambda: closed.append("content"))
    controller.register(
        "environment",
        dependencies=("content",),
        retire=lambda: closed.append("environment"),
    )
    lease = controller.acquire("graph-attempt:1")

    with pytest.raises(RuntimeError, match="active leases"):
        controller.retire_all()
    assert closed == []

    lease.release()
    retired = controller.retire_all()

    assert closed == ["environment", "content"]
    assert controller.root_domain_id in retired
    assert all(
        row.phase is ResourceLifetimePhase.RETIRED for row in controller.snapshot()
    )
    authority.verify_projection_rebuild()


def test_resource_lifetime_dag_is_acyclic_by_registration_construction(tmp_path):
    authority, controller = _controller(tmp_path)
    with pytest.raises(ValueError, match="dependencies must already exist"):
        controller.register(
            "environment",
            dependencies=("future",),
            retire=lambda: None,
        )
    controller.register("content", retire=lambda: None)
    controller.register(
        "environment",
        dependencies=("content",),
        retire=lambda: None,
    )
    assert controller.quiescent is True
    authority.verify_projection_rebuild()


def test_resource_lifetime_lease_is_affine_and_retired_domains_reject_new_borrowers(tmp_path):
    authority, controller = _controller(tmp_path)
    lease = controller.acquire("graph-attempt:1")
    lease.release()
    lease.release()
    assert lease.released is True
    controller.retire_all()

    with pytest.raises(RuntimeError, match="does not admit new leases"):
        controller.acquire("graph-attempt:2")
    authority.verify_projection_rebuild()


def test_resource_lifetime_generation_and_lease_are_universal_authority_facts(tmp_path):
    authority, controller = _controller(tmp_path)
    lease = controller.acquire("graph-attempt:1")
    snapshot = authority.snapshot()
    root = next(row for row in controller.snapshot() if row.domain_id == controller.root_domain_id)

    generation = snapshot.generation_for(root.resource_key)
    assert generation is not None
    assert generation.generation == lease.generation == root.generation
    assert tuple(authority.active_leases(root.resource_key)) == (lease.unit,)

    lease.release()
    controller.retire_all()
    authority.verify_projection_rebuild()
