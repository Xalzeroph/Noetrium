from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentProfileMaterialization,
    EnvironmentProfileRevision,
)
from noetrium_platform.capabilities.environment.catalog.runtime import (
    SQLiteExecutionEnvironmentCatalog,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry


def test_concurrent_reusable_acquisition_never_double_assigns_instance(tmp_path) -> None:
    database = tmp_path / "environment-pool.sqlite"
    scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
    scopes = SQLiteScopeRegistry(database)
    scopes.register(scope, PLATFORM_SCOPE)

    profile_id = "web-scale"
    profile_revision = "a" * 64
    runtime_identity_digest = "b" * 64
    runtime_reference = "container:web-scale"
    catalog = SQLiteExecutionEnvironmentCatalog(database, scopes)
    catalog.register_profile_revision(
        EnvironmentProfileRevision(
            profile_id,
            "web",
            profile_revision,
        )
    )
    materialization = EnvironmentProfileMaterialization(
        profile_id,
        profile_revision,
        "e" * 64,
        runtime_identity_digest,
        "f" * 64,
        runtime_reference,
    )
    catalog.register_profile_materialization(materialization)

    pool_size = 6
    for index in range(pool_size):
        catalog.register_instance(
            EnvironmentInstance(
                f"env-{index:02d}",
                "c" * 64,
                "docker",
                runtime_reference,
                runtime_identity_digest,
                materialization.materialization_digest,
                scope,
                profile_id,
                profile_revision,
            )
        )

    def acquire(index: int):
        local_scopes = SQLiteScopeRegistry(database)
        local = SQLiteExecutionEnvironmentCatalog(database, local_scopes)
        return local.acquire_reusable_instance(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization.materialization_digest,
            binding_id=f"binding-{index:02d}",
            role=f"runner-{index:02d}",
            scope=scope,
        )

    with ThreadPoolExecutor(max_workers=pool_size) as executor:
        acquisitions = tuple(executor.map(acquire, range(pool_size)))

    instance_ids = tuple(row.instance.instance_id for row in acquisitions)
    assert len(set(instance_ids)) == pool_size
    assert all(row.instance.generation == 1 for row in acquisitions)
    assert all(row.binding.instance_id == row.instance.instance_id for row in acquisitions)

    observer = SQLiteExecutionEnvironmentCatalog(
        database,
        SQLiteScopeRegistry(database),
    )
    assert observer.reusable_instances(
        profile_id,
        profile_revision,
        runtime_identity_digest,
        materialization.materialization_digest,
    ) == ()

    for row in acquisitions:
        observer.unbind(row.binding.role, row.binding.scope)
        observer.release_instance(
            row.instance.instance_id,
            cleanliness=EnvironmentCleanlinessProof(
                row.instance.instance_id,
                profile_revision,
                runtime_identity_digest,
                materialization.materialization_digest,
                row.instance.generation,
                EnvironmentCleanlinessKind.PROVIDER_RESET_VERIFIED,
                "d" * 64,
            ),
        )

    reacquired = observer.acquire_reusable_instance(
        profile_id,
        profile_revision,
        runtime_identity_digest,
        materialization.materialization_digest,
        binding_id="binding-reacquired",
        role="runner-reacquired",
        scope=scope,
    )
    assert reacquired.instance.instance_id == min(instance_ids)
    assert reacquired.instance.generation == 2


def test_concurrent_empty_pool_provision_and_acquire_is_atomic(tmp_path) -> None:
    database = tmp_path / "environment-provision.sqlite"
    scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
    scopes = SQLiteScopeRegistry(database)
    scopes.register(scope, PLATFORM_SCOPE)
    profile_id = "minecraft-scale"
    profile_revision = "1" * 64
    runtime_identity_digest = "2" * 64
    runtime_reference = "container:minecraft-scale"
    catalog = SQLiteExecutionEnvironmentCatalog(database, scopes)
    catalog.register_profile_revision(
        EnvironmentProfileRevision(profile_id, "minecraft", profile_revision)
    )
    materialization = EnvironmentProfileMaterialization(
        profile_id,
        profile_revision,
        "3" * 64,
        runtime_identity_digest,
        "4" * 64,
        runtime_reference,
    )
    catalog.register_profile_materialization(materialization)

    count = 8

    def provision(index: int):
        local = SQLiteExecutionEnvironmentCatalog(
            database, SQLiteScopeRegistry(database)
        )
        return local.provision_reusable_instance(
            EnvironmentInstance(
                f"minecraft-slot-{index:02d}",
                "5" * 64,
                "minecraft.mineflayer",
                runtime_reference,
                runtime_identity_digest,
                materialization.materialization_digest,
                scope,
                profile_id,
                profile_revision,
            ),
            binding_id=f"binding-{index:02d}",
            role=f"minecraft.assignment.{index:02d}",
            scope=scope,
        )

    with ThreadPoolExecutor(max_workers=count) as executor:
        rows = tuple(executor.map(provision, range(count)))

    assert len({row.instance.instance_id for row in rows}) == count
    assert all(row.instance.state.value == "in_use" for row in rows)
    assert all(row.instance.generation == 1 for row in rows)
    observer = SQLiteExecutionEnvironmentCatalog(
        database, SQLiteScopeRegistry(database)
    )
    assert len(observer.bindings()) == count
    assert observer.reusable_instances(
        profile_id,
        profile_revision,
        runtime_identity_digest,
        materialization.materialization_digest,
    ) == ()
