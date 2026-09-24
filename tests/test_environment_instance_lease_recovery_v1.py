from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceState,
    EnvironmentProfileMaterialization,
    EnvironmentProfileRevision,
)
from noetrium_platform.capabilities.environment.catalog.runtime import (
    ExecutionEnvironmentCatalog,
    SQLiteExecutionEnvironmentCatalog,
)
from noetrium_platform.composition.environment_instance_leases import (
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceLeasePolicy,
)
from noetrium_platform.foundation.scope.api import (
    PLATFORM_SCOPE,
    ScopeIdentity,
    ScopeKind,
)
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteResourceLeaseRegistry,
)


PROFILE_ID = "web-lease-test"
PROFILE_REVISION = "a" * 64
RUNTIME_DIGEST = "b" * 64
BUILD_DIGEST = "c" * 64
RECEIPT_DIGEST = "d" * 64
RUNTIME_REFERENCE = "container:web-lease-test"


def _scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.WORKSPACE, "workspace-lease-test")


def _prepare_catalog(catalog, scope: ScopeIdentity):
    catalog.register_profile_revision(
        EnvironmentProfileRevision(PROFILE_ID, "web", PROFILE_REVISION)
    )
    materialization = EnvironmentProfileMaterialization(
        PROFILE_ID,
        PROFILE_REVISION,
        BUILD_DIGEST,
        RUNTIME_DIGEST,
        RECEIPT_DIGEST,
        RUNTIME_REFERENCE,
    )
    catalog.register_profile_materialization(materialization)
    instance = EnvironmentInstance(
        "environment-instance-a",
        "e" * 64,
        "docker",
        RUNTIME_REFERENCE,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        scope,
        PROFILE_ID,
        PROFILE_REVISION,
    )
    catalog.register_instance(instance)
    return materialization, instance


def _cleanliness(handle, materialization):
    return EnvironmentCleanlinessProof(
        handle.instance.instance_id,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        handle.instance.generation,
        EnvironmentCleanlinessKind.PROVIDER_RESET_VERIFIED,
        "f" * 64,
    )


def test_environment_instance_release_is_lease_first_and_returns_clean_only_with_proof() -> None:
    scopes = InMemoryScopeRegistry()
    scope = _scope()
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = ExecutionEnvironmentCatalog(scopes)
    materialization, instance = _prepare_catalog(catalog, scope)
    resources = InMemoryResourceLeaseRegistry()
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=resources,
        reconcile_on_start=False,
    )

    handle = authority.acquire_reusable_instance(
        PROFILE_ID,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        binding_id="binding-a",
        role="runner",
        scope=scope,
    )
    resource = ResourceIdentity(
        ResourceKind.EXECUTION_ENVIRONMENT,
        instance.instance_id,
    )
    assert handle.instance.state is EnvironmentInstanceState.IN_USE
    assert resources.active_for(resource) == (handle.lease,)

    released = authority.release(
        handle,
        cleanliness=_cleanliness(handle, materialization),
    )
    assert released.state is EnvironmentInstanceState.CLEAN
    assert catalog.bindings() == ()
    assert resources.active_for(resource) == ()


def test_environment_instance_expired_lease_becomes_dirty_and_is_not_reused() -> None:
    scopes = InMemoryScopeRegistry()
    scope = _scope()
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = ExecutionEnvironmentCatalog(scopes)
    materialization, _instance = _prepare_catalog(catalog, scope)
    resources = InMemoryResourceLeaseRegistry()
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=resources,
        policy=EnvironmentInstanceLeasePolicy(
            ttl_seconds=0.1,
            renewal_interval_seconds=0.05,
        ),
        reconcile_on_start=False,
    )
    handle = authority.acquire_reusable_instance(
        PROFILE_ID,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        binding_id="binding-expiring",
        role="runner",
        scope=scope,
    )
    assert handle.lease.expires_at_epoch_s is not None

    report = authority.reconcile(now=handle.lease.expires_at_epoch_s + 1.0)
    assert report.dirtied_instance_ids == (handle.instance.instance_id,)
    assert catalog.bindings() == ()
    current = catalog.instances()[0]
    assert current.state is EnvironmentInstanceState.DIRTY
    assert (
        catalog.reusable_instances(
            PROFILE_ID,
            PROFILE_REVISION,
            RUNTIME_DIGEST,
            materialization.materialization_digest,
        )
        == ()
    )


def test_environment_instance_restart_reconciliation_persists_dirty_state(tmp_path) -> None:
    resource_db = tmp_path / "resource.sqlite"
    environment_db = tmp_path / "environment.sqlite"
    scope = _scope()
    scopes = SQLiteScopeRegistry(resource_db)
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = SQLiteExecutionEnvironmentCatalog(environment_db, scopes)
    materialization, _instance = _prepare_catalog(catalog, scope)
    resources = SQLiteResourceLeaseRegistry(resource_db)
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=resources,
        policy=EnvironmentInstanceLeasePolicy(
            ttl_seconds=0.1,
            renewal_interval_seconds=0.05,
        ),
        reconcile_on_start=False,
    )
    handle = authority.acquire_reusable_instance(
        PROFILE_ID,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        binding_id="binding-restart",
        role="runner",
        scope=scope,
    )
    assert handle.lease.expires_at_epoch_s is not None

    restarted = EnvironmentInstanceLeaseAuthority(
        catalog=SQLiteExecutionEnvironmentCatalog(
            environment_db,
            SQLiteScopeRegistry(resource_db),
        ),
        ownership=SQLiteResourceLeaseRegistry(resource_db),
        leases=SQLiteResourceLeaseRegistry(resource_db),
        reconcile_on_start=False,
    )
    report = restarted.reconcile(now=handle.lease.expires_at_epoch_s + 1.0)
    assert report.dirtied_instance_ids == (handle.instance.instance_id,)

    reopened = SQLiteExecutionEnvironmentCatalog(
        environment_db,
        SQLiteScopeRegistry(resource_db),
    )
    assert reopened.bindings() == ()
    assert reopened.instances()[0].state is EnvironmentInstanceState.DIRTY


def test_environment_instance_lease_conflict_compensates_to_dirty() -> None:
    scopes = InMemoryScopeRegistry()
    scope = _scope()
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = ExecutionEnvironmentCatalog(scopes)
    materialization, instance = _prepare_catalog(catalog, scope)
    resources = InMemoryResourceLeaseRegistry()
    resource = ResourceIdentity(
        ResourceKind.EXECUTION_ENVIRONMENT,
        instance.instance_id,
    )
    resources.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    resources.acquire(
        ResourceLease(
            "conflicting-environment-holder",
            resource,
            scope,
            "simulated stale owner",
        ),
        ttl_seconds=60.0,
    )
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=resources,
        reconcile_on_start=False,
    )

    with pytest.raises(RuntimeError):
        authority.acquire_reusable_instance(
            PROFILE_ID,
            PROFILE_REVISION,
            RUNTIME_DIGEST,
            materialization.materialization_digest,
            binding_id="binding-conflict",
            role="runner",
            scope=scope,
        )

    assert catalog.bindings() == ()
    assert catalog.instances()[0].state is EnvironmentInstanceState.DIRTY


def test_environment_shutdown_cleanup_marks_live_generation_dirty() -> None:
    scopes = InMemoryScopeRegistry()
    scope = _scope()
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = ExecutionEnvironmentCatalog(scopes)
    materialization, instance = _prepare_catalog(catalog, scope)
    resources = InMemoryResourceLeaseRegistry()
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=resources,
        reconcile_on_start=False,
    )
    handle = authority.acquire_reusable_instance(
        PROFILE_ID,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        binding_id="binding-shutdown",
        role="runner",
        scope=scope,
    )

    report = authority.shutdown_cleanup()

    assert report.dirtied_instance_ids == (instance.instance_id,)
    assert report.released_orphan_lease_ids == (handle.lease.lease_id,)
    assert catalog.bindings() == ()
    assert catalog.instances()[0].state is EnvironmentInstanceState.DIRTY
    assert resources.active_for(
        ResourceIdentity(ResourceKind.EXECUTION_ENVIRONMENT, instance.instance_id)
    ) == ()


class _FailOnceLeaseRelease:
    def __init__(self, delegate, *, commit_before_error: bool) -> None:
        self.delegate = delegate
        self.commit_before_error = commit_before_error
        self.release_calls = 0

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def release(self, lease_id: str, *, fencing_token: int, now=None):
        self.release_calls += 1
        if self.release_calls == 1:
            if self.commit_before_error:
                self.delegate.release(
                    lease_id,
                    fencing_token=fencing_token,
                    now=now,
                )
            raise OSError("simulated durable lease release I/O ambiguity")
        return self.delegate.release(
            lease_id,
            fencing_token=fencing_token,
            now=now,
        )


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_environment_instance_release_retries_uncertain_durable_release_without_promoting_clean(
    commit_before_error: bool,
) -> None:
    scopes = InMemoryScopeRegistry()
    scope = _scope()
    scopes.register(scope, PLATFORM_SCOPE)
    catalog = ExecutionEnvironmentCatalog(scopes)
    materialization, instance = _prepare_catalog(catalog, scope)
    resources = InMemoryResourceLeaseRegistry()
    leases = _FailOnceLeaseRelease(
        resources,
        commit_before_error=commit_before_error,
    )
    authority = EnvironmentInstanceLeaseAuthority(
        catalog=catalog,
        ownership=resources,
        leases=leases,
        reconcile_on_start=False,
    )
    handle = authority.acquire_reusable_instance(
        PROFILE_ID,
        PROFILE_REVISION,
        RUNTIME_DIGEST,
        materialization.materialization_digest,
        binding_id="binding-release-retry",
        role="runner",
        scope=scope,
    )
    resource = ResourceIdentity(
        ResourceKind.EXECUTION_ENVIRONMENT,
        instance.instance_id,
    )
    proof = _cleanliness(handle, materialization)

    with pytest.raises(OSError, match="release I/O ambiguity"):
        authority.release(handle, cleanliness=proof)

    assert catalog.bindings() == ()
    assert catalog.instances()[0].state is EnvironmentInstanceState.DIRTY
    if commit_before_error:
        assert resources.active_for(resource) == ()
    else:
        assert resources.active_for(resource) == (handle.lease,)

    converged = authority.release(handle, cleanliness=proof)

    assert converged.state is EnvironmentInstanceState.DIRTY
    assert resources.active_for(resource) == ()
    assert leases.release_calls == 2
