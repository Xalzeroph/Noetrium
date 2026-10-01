from __future__ import annotations

from noetrium_platform.infrastructure.resources.lease.runtime import LocalLeaseClock, ManualLeaseClock, ResourceLeaseRegistry

from tests_support import model_role_for_test

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)

from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.infrastructure.resources.allocation.api import EndpointAllocationRequest, EndpointProbeResult, NetworkEndpoint
from noetrium_platform.infrastructure.resources.compute.api import ComputeHost, ComputeRequirement
from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentAssignment,
    EnvironmentBinding,
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceState,
    EnvironmentProfileMaterialization,
    EnvironmentProfileLifecycle,
    EnvironmentProfileRevision,
    EnvironmentSpec,
    ExecutionEnvironmentKind,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteEndpointAllocationStore
from noetrium_platform.infrastructure.resources.allocation.runtime import AtomicEndpointAllocator
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
    ResourceOwnership,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ResourceLeaseConflict
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.portfolio.api import (
    ProgramSpec,
    ProjectIdentity,
    ProjectManifest,
    ProjectSpec,
    ProjectToolProvenance,
    WorkspaceSpec,
)
from noetrium_platform.research.experimentation.lifecycle.api import RunIdentity
from noetrium_platform.research.experimentation.lifecycle.study import StudySpec
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentSpec


def _environment_gc_closures(
    retained_authority: DurableCarrierClosureAuthority | None = None,
    retained_reference_id: str | None = None,
) -> tuple[DurableCarrierReferenceClosure, ...]:
    return tuple(
        DurableCarrierReferenceClosure(
            authority,
            str(index) * 64,
            (
                (retained_reference_id,)
                if authority is retained_authority
                and retained_reference_id is not None
                else ()
            ),
        )
        for index, authority in enumerate(
            (
                DurableCarrierClosureAuthority.EVIDENCE,
                DurableCarrierClosureAuthority.EXECUTION,
                DurableCarrierClosureAuthority.RECOVERY,
            ),
            start=1,
        )
    )




def _register_materialization(
    catalog,
    *,
    profile_id: str,
    profile_revision: str,
    runtime_identity_digest: str,
    runtime_reference: str,
) -> EnvironmentProfileMaterialization:
    materialization = EnvironmentProfileMaterialization(
        profile_id,
        profile_revision,
        "b" * 64,
        runtime_identity_digest,
        "c" * 64,
        runtime_reference,
    )
    catalog.register_profile_materialization(materialization)
    return materialization

class _AvailableProbe:
    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        return EndpointProbeResult(endpoint, True, "test probe")


class DurableResourceAuthoritiesTests(TestCase):
    def test_scope_and_lease_survive_rebuild_and_fence_conflicts(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "platform.sqlite"
            workspace = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            resource = ResourceIdentity(ResourceKind.COMPUTE, "host-1")
            scopes = SQLiteScopeRegistry(database)
            scopes.register(workspace, PLATFORM_SCOPE)
            owners = ResourceLeaseRegistry(database)
            owner = ResourceOwner(resource, PLATFORM_SCOPE, ResourceOwnership.PLATFORM_MANAGED)
            owners.register_owner(owner)
            lease = ResourceLease("lease-1", resource, workspace, "test allocation")
            granted = owners.acquire(lease)

            restored_scopes = SQLiteScopeRegistry(database)
            restored_owners = ResourceLeaseRegistry(database)
            self.assertEqual(restored_scopes.ancestry(workspace), (workspace, PLATFORM_SCOPE))
            self.assertEqual(restored_owners.get("lease-1"), granted)
            with self.assertRaises(ResourceLeaseConflict):
                restored_owners.acquire(ResourceLease("lease-2", resource, workspace, "competing allocation"))

    def test_durable_lease_retention_survives_time_and_finite_heartbeat(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "retained.sqlite"
            clock = ManualLeaseClock(
                elapsed_seconds=1.0,
                wall_epoch_seconds=100.0,
            )
            registry = ResourceLeaseRegistry(database, clock=clock)
            resource = ResourceIdentity(ResourceKind.COMPUTE, "retained-compute")
            registry.register_owner(
                ResourceOwner(
                    resource,
                    PLATFORM_SCOPE,
                    ResourceOwnership.PLATFORM_MANAGED,
                )
            )
            granted = registry.acquire(
                ResourceLease(
                    "retained-lease",
                    resource,
                    PLATFORM_SCOPE,
                    "warm-model-realization",
                ),
                ttl_seconds=10.0,
            )
            retained = registry.renew(
                granted.lease_id,
                fencing_token=granted.fencing_token,
                ttl_seconds=None,
            )
            self.assertIsNone(retained.expires_at_epoch_s)
            self.assertEqual(retained.fencing_token, granted.fencing_token)

            clock.advance(1000.0)
            self.assertEqual(registry.get(granted.lease_id), retained)

            heartbeat = registry.renew(
                retained.lease_id,
                fencing_token=retained.fencing_token,
                ttl_seconds=30.0,
            )
            self.assertIsNone(heartbeat.expires_at_epoch_s)
            self.assertEqual(heartbeat.fencing_token, retained.fencing_token)

    def test_endpoint_allocation_survives_rebuild_and_release_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "platform.sqlite"
            workspace = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            scopes = SQLiteScopeRegistry(database)
            scopes.register(workspace, PLATFORM_SCOPE)
            leases = ResourceLeaseRegistry(database)
            store = SQLiteEndpointAllocationStore(database, clock=LocalLeaseClock())
            allocator = AtomicEndpointAllocator(
                reservations=store,
                probe=_AvailableProbe(),
            )
            request = EndpointAllocationRequest(
                allocation_id="allocation-1",
                holder_scope=workspace,
                purpose="minecraft test server",
                host="127.0.0.1",
                candidate_ports=(25565, 25566),
            )
            allocation = allocator.allocate(request)
            restored = AtomicEndpointAllocator(
                reservations=SQLiteEndpointAllocationStore(database, clock=LocalLeaseClock()),
                probe=_AvailableProbe(),
            )
            self.assertEqual(restored.allocate(request), allocation)
            released = restored.release(allocation)
            self.assertEqual(restored.release(allocation), released)
            self.assertEqual(restored.active(), ())

    def test_durable_platform_meta_uses_one_authority_database(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_platform_meta(root)
            workspace = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            first.scopes.register(workspace, PLATFORM_SCOPE)
            second = build_platform_meta(root)
            self.assertTrue(second.scopes.contains(workspace))
            self.assertEqual((root / "platform-meta.sqlite").is_file(), True)

    def test_durable_portfolio_survives_rebuild_with_canonical_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_platform_meta(root)
            first.portfolio.register_workspace(WorkspaceSpec("workspace", "Workspace"))
            first.portfolio.register_program(ProgramSpec("program", "workspace", "Program"))
            manifest = ProjectManifest(
                ProjectSpec(ProjectIdentity("project", "1.0.0"), "program", "Project"),
                "template-1",
                ProjectToolProvenance("tool", "1.0.0", "0" * 64),
            )
            first.portfolio.register_project(manifest)

            second = build_platform_meta(root)
            self.assertEqual(second.portfolio.workspace("workspace").name, "Workspace")
            self.assertEqual(second.portfolio.program("program").workspace_id, "workspace")
            self.assertEqual(second.portfolio.project("project"), manifest)
            self.assertEqual(second.portfolio.projects(program_id="program"), (manifest,))

    def test_durable_experimentation_survives_rebuild(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = build_platform_meta(root)
            first.portfolio.register_workspace(WorkspaceSpec("workspace", "Workspace"))
            first.portfolio.register_program(ProgramSpec("program", "workspace", "Program"))
            manifest = ProjectManifest(
                ProjectSpec(ProjectIdentity("project", "1.0.0"), "program", "Project"),
                "template-1",
                ProjectToolProvenance("tool", "1.0.0", "0" * 64),
            )
            first.portfolio.register_project(manifest)
            first.experimentation.register_study(
                StudySpec("study", "project", "Study", ("experiment",))
            )
            experiment = ExperimentSpec(
                "experiment", "study", "project", (), (model_role_for_test(),),
                "1" * 64, "2" * 64, 1, "protocol", "3" * 64
            )
            first.experimentation.register_experiment(experiment)
            run = RunIdentity("run", "session", "trace")
            first.experimentation.register_run("experiment", run)
            second = build_platform_meta(root)
            self.assertEqual(second.experimentation.study("study").name, "Study")
            self.assertEqual(second.experimentation.experiment("experiment"), experiment)
            self.assertEqual(second.experimentation.experiments(study_id="study"), (experiment,))

    def test_durable_compute_inventory_and_allocations_survive_rebuild(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            first = build_platform_meta(root)
            first.scopes.register(scope, PLATFORM_SCOPE)
            first.compute_inventory.register_host(
                ComputeHost("host-1", scope, 8, 1024)
            )
            requirement = ComputeRequirement(cpu_cores=2, memory_bytes=256)
            allocation = first.compute_scheduler.allocate("compute-1", scope, requirement)
            second = build_platform_meta(root)
            self.assertEqual(second.compute_inventory.host("host-1").cpu_cores, 8)
            self.assertEqual(second.compute_scheduler.allocations(), (allocation,))
            second.compute_scheduler.release(allocation)
            self.assertEqual(second.compute_scheduler.allocations(), ())

    def test_environment_instance_reuse_is_generation_fenced_and_gc_safe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            meta = build_platform_meta(root)
            meta.scopes.register(scope, PLATFORM_SCOPE)
            revision = "a" * 64
            runtime_digest = "d" * 64
            meta.environments.register_profile_revision(
                EnvironmentProfileRevision(
                    "web-default",
                    "web",
                    revision,
                )
            )
            materialization = _register_materialization(
                meta.environments,
                profile_id="web-default",
                profile_revision=revision,
                runtime_identity_digest=runtime_digest,
                runtime_reference="container:env-reuse",
            )
            instance = EnvironmentInstance(
                "env-reuse",
                "b" * 64,
                "docker",
                "container:env-reuse",
                runtime_digest,
                materialization.materialization_digest,
                scope,
                "web-default",
                revision,
            )
            meta.environments.register_instance(instance)
            self.assertEqual(
                meta.environments.reusable_instances(
                    "web-default", revision, runtime_digest, materialization.materialization_digest
                ),
                (instance,),
            )

            with self.assertRaises(KeyError):
                meta.environment_instance_leases.acquire_reusable_instance(
                    "web-default",
                    revision,
                    "e" * 64,
                    materialization.materialization_digest,
                    binding_id="wrong-runtime",
                    role="runner",
                    scope=scope,
                )

            acquisition = meta.environment_instance_leases.acquire_reusable_instance(
                "web-default",
                revision,
                runtime_digest,
                materialization.materialization_digest,
                binding_id="binding-reuse",
                role="runner",
                scope=scope,
            )
            binding = acquisition.binding
            self.assertEqual(binding.instance_id, "env-reuse")
            self.assertIs(
                acquisition.instance.state,
                EnvironmentInstanceState.IN_USE,
            )
            self.assertEqual(acquisition.instance.generation, 1)
            self.assertEqual(
                meta.environments.reusable_instances(
                    "web-default", revision, runtime_digest, materialization.materialization_digest
                ),
                (),
            )
            restored_acquired = build_platform_meta(root)
            self.assertEqual(
                restored_acquired.environments.binding("runner", scope),
                binding,
            )
            dirty = meta.environment_instance_leases.release(acquisition)
            self.assertIs(dirty.state, EnvironmentInstanceState.DIRTY)
            self.assertEqual(dirty.generation, 1)

            proof = EnvironmentCleanlinessProof(
                "env-reuse",
                revision,
                runtime_digest,
                materialization.materialization_digest,
                dirty.generation,
                EnvironmentCleanlinessKind.OVERLAY_DESTROYED,
                "c" * 64,
            )
            clean = meta.environments.release_instance(
                "env-reuse",
                cleanliness=proof,
            )
            self.assertIs(clean.state, EnvironmentInstanceState.CLEAN)
            self.assertEqual(
                meta.environments.reusable_instances(
                    "web-default", revision, runtime_digest, materialization.materialization_digest
                ),
                (clean,),
            )

            reacquisition = meta.environment_instance_leases.acquire_reusable_instance(
                "web-default",
                revision,
                runtime_digest,
                materialization.materialization_digest,
                binding_id=binding.binding_id,
                role=binding.role,
                scope=binding.scope,
            )
            self.assertEqual(reacquisition.binding, binding)
            self.assertEqual(reacquisition.instance.generation, 2)
            with self.assertRaises(RuntimeError):
                meta.environment_instance_leases.release(
                    reacquisition,
                    cleanliness=proof,
                )
            meta.environment_instance_leases.reconcile()
            destroyed = meta.environments.destroy_instance("env-reuse")
            self.assertIs(destroyed.state, EnvironmentInstanceState.DESTROYED)

            unproven = meta.environments.assess_profile_gc(
                "web-default",
                revision,
            )
            self.assertFalse(unproven.closure_complete)
            self.assertFalse(unproven.eligible)

            local = meta.environments.assess_profile_gc(
                "web-default",
                revision,
                closures=_environment_gc_closures(),
            )
            self.assertTrue(local.closure_complete)
            self.assertTrue(local.eligible)
            resumable = meta.environments.assess_profile_gc(
                "web-default",
                revision,
                closures=_environment_gc_closures(
                    DurableCarrierClosureAuthority.EXECUTION,
                    "run-1",
                ),
            )
            self.assertFalse(resumable.eligible)
            evidence = meta.environments.assess_profile_gc(
                "web-default",
                revision,
                closures=_environment_gc_closures(
                    DurableCarrierClosureAuthority.EVIDENCE,
                    "evidence-1",
                ),
            )
            self.assertFalse(evidence.eligible)
            recovery = meta.environments.assess_profile_gc(
                "web-default",
                revision,
                closures=_environment_gc_closures(
                    DurableCarrierClosureAuthority.RECOVERY,
                    "checkpoint-1",
                ),
            )
            self.assertFalse(recovery.eligible)

            restored = build_platform_meta(root)
            restored_unproven = restored.environments.assess_profile_gc(
                "web-default",
                revision,
            )
            self.assertFalse(restored_unproven.eligible)
            restored_gc = restored.environments.assess_profile_gc(
                "web-default",
                revision,
                closures=_environment_gc_closures(),
            )
            self.assertTrue(restored_gc.eligible)


    def test_environment_exact_runtime_gc_does_not_collapse_profile_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            meta = build_platform_meta(root)
            meta.scopes.register(scope, PLATFORM_SCOPE)
            revision = "a" * 64
            runtime_a = "b" * 64
            runtime_b = "c" * 64
            meta.environments.register_profile_revision(
                EnvironmentProfileRevision("web-multi-runtime", "web", revision)
            )
            materialization_a = _register_materialization(
                meta.environments,
                profile_id="web-multi-runtime",
                profile_revision=revision,
                runtime_identity_digest=runtime_a,
                runtime_reference="container:runtime-a",
            )
            materialization_b = _register_materialization(
                meta.environments,
                profile_id="web-multi-runtime",
                profile_revision=revision,
                runtime_identity_digest=runtime_b,
                runtime_reference="container:runtime-b",
            )
            first = EnvironmentInstance(
                "env-runtime-a",
                "d" * 64,
                "docker",
                "container:runtime-a",
                runtime_a,
                materialization_a.materialization_digest,
                scope,
                "web-multi-runtime",
                revision,
            )
            second = EnvironmentInstance(
                "env-runtime-b",
                "e" * 64,
                "docker",
                "container:runtime-b",
                runtime_b,
                materialization_b.materialization_digest,
                scope,
                "web-multi-runtime",
                revision,
            )
            meta.environments.register_instance(first)
            meta.environments.register_instance(second)
            meta.environments.destroy_instance(first.instance_id)

            exact_a = meta.environments.assess_runtime_gc(
                "web-multi-runtime",
                revision,
                runtime_a,
                closures=_environment_gc_closures(),
            )
            self.assertTrue(exact_a.eligible)
            self.assertEqual(exact_a.local.instance_ids, (first.instance_id,))

            exact_b = meta.environments.assess_runtime_gc(
                "web-multi-runtime",
                revision,
                runtime_b,
                closures=_environment_gc_closures(),
            )
            self.assertFalse(exact_b.eligible)
            self.assertEqual(
                exact_b.local.blocking_instance_ids,
                (second.instance_id,),
            )

            whole_profile = meta.environments.assess_profile_gc(
                "web-multi-runtime",
                revision,
                closures=_environment_gc_closures(),
            )
            self.assertFalse(whole_profile.eligible)

            restored = build_platform_meta(root)
            restored_exact_a = restored.environments.assess_runtime_gc(
                "web-multi-runtime",
                revision,
                runtime_a,
                closures=_environment_gc_closures(),
            )
            self.assertTrue(restored_exact_a.eligible)

            restored.environments.destroy_instance(second.instance_id)
            final_profile = restored.environments.assess_profile_gc(
                "web-multi-runtime",
                revision,
                closures=_environment_gc_closures(),
            )
            self.assertTrue(final_profile.eligible)


    def test_environment_profile_lifecycle_is_runtime_admission_truth(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            other_scope = ScopeIdentity(ScopeKind.WORKSPACE, "other-workspace")
            meta = build_platform_meta(root)
            meta.scopes.register(scope, PLATFORM_SCOPE)
            meta.scopes.register(other_scope, PLATFORM_SCOPE)
            revision = "4" * 64
            runtime_digest = "5" * 64
            profile = EnvironmentProfileRevision(
                "web-lifecycle",
                "web",
                revision,
            )
            meta.environments.register_profile_revision(profile)
            initial_materialization = _register_materialization(
                meta.environments,
                profile_id=profile.profile_id,
                profile_revision=profile.profile_revision,
                runtime_identity_digest=runtime_digest,
                runtime_reference="container:env-lifecycle",
            )
            replacement_materialization = _register_materialization(
                meta.environments,
                profile_id=profile.profile_id,
                profile_revision=profile.profile_revision,
                runtime_identity_digest=runtime_digest,
                runtime_reference="container:env-lifecycle",
            )
            wrong_scope_materialization = _register_materialization(
                meta.environments,
                profile_id=profile.profile_id,
                profile_revision=profile.profile_revision,
                runtime_identity_digest=runtime_digest,
                runtime_reference="container:env-lifecycle",
            )
            retired_materialization = _register_materialization(
                meta.environments,
                profile_id=profile.profile_id,
                profile_revision=profile.profile_revision,
                runtime_identity_digest=runtime_digest,
                runtime_reference="container:env-lifecycle",
            )
            instance = EnvironmentInstance(
                "env-lifecycle",
                "6" * 64,
                "docker",
                "container:env-lifecycle",
                runtime_digest,
                initial_materialization.materialization_digest,
                scope,
                profile.profile_id,
                profile.profile_revision,
            )
            meta.environments.register_instance(instance)

            pinned = meta.environment_instance_leases.acquire_reusable_instance(
                profile.profile_id,
                profile.profile_revision,
                runtime_digest,
                initial_materialization.materialization_digest,
                binding_id="pinned-binding",
                role="runner",
                scope=scope,
            )
            self.assertEqual(pinned.instance.generation, 1)

            draining = meta.environments.transition_profile_revision(
                profile.profile_id,
                profile.profile_revision,
                EnvironmentProfileLifecycle.DRAINING,
            )
            self.assertIs(
                draining.lifecycle,
                EnvironmentProfileLifecycle.DRAINING,
            )
            with self.assertRaises(RuntimeError):
                meta.environment_instance_leases.acquire_reusable_instance(
                    profile.profile_id,
                    profile.profile_revision,
                    runtime_digest,
                    initial_materialization.materialization_digest,
                    binding_id="new-work",
                    role="runner-2",
                    scope=scope,
                )

            replacement_instance = EnvironmentInstance(
                "env-lifecycle-replacement",
                "8" * 64,
                "docker",
                "container:env-lifecycle",
                runtime_digest,
                initial_materialization.materialization_digest,
                scope,
                profile.profile_id,
                profile.profile_revision,
            )
            with self.assertRaises(RuntimeError):
                meta.environments.register_instance(replacement_instance)
            with self.assertRaises(RuntimeError):
                meta.environments.register_recovery_instance(
                    EnvironmentInstance(
                        "env-wrong-scope",
                        "9" * 64,
                        "docker",
                        "container:env-lifecycle",
                        runtime_digest,
                        initial_materialization.materialization_digest,
                        other_scope,
                        profile.profile_id,
                        profile.profile_revision,
                    ),
                    role="runner",
                    scope=other_scope,
                )

            meta.environments.register_recovery_instance(
                replacement_instance,
                role="runner",
                scope=scope,
            )
            recovered = meta.environment_instance_leases.recover_reusable_instance(
                profile.profile_id,
                profile.profile_revision,
                runtime_digest,
                initial_materialization.materialization_digest,
                role="runner",
                scope=scope,
            )
            self.assertEqual(recovered.binding.binding_id, "pinned-binding")
            self.assertEqual(
                recovered.binding.instance_id,
                replacement_instance.instance_id,
            )
            self.assertEqual(recovered.instance.generation, 1)

            restored_pinned = build_platform_meta(root)
            self.assertEqual(
                restored_pinned.environments.binding("runner", scope),
                recovered.binding,
            )

            meta.environment_instance_leases.release(
                recovered,
                cleanliness=EnvironmentCleanlinessProof(
                    recovered.instance.instance_id,
                    revision,
                    runtime_digest,
                    initial_materialization.materialization_digest,
                    recovered.instance.generation,
                    EnvironmentCleanlinessKind.PROVIDER_RESET_VERIFIED,
                    "7" * 64,
                ),
            )

            retired = meta.environments.transition_profile_revision(
                profile.profile_id,
                profile.profile_revision,
                EnvironmentProfileLifecycle.RETIRED,
            )
            self.assertIs(
                retired.lifecycle,
                EnvironmentProfileLifecycle.RETIRED,
            )
            with self.assertRaises(RuntimeError):
                meta.environment_instance_leases.acquire_reusable_instance(
                    profile.profile_id,
                    profile.profile_revision,
                    runtime_digest,
                    initial_materialization.materialization_digest,
                    binding_id="new-after-retire",
                    role="runner",
                    scope=scope,
                )
            with self.assertRaises(RuntimeError):
                meta.environments.register_recovery_instance(
                    EnvironmentInstance(
                        "env-retired-replacement",
                        "a" * 64,
                        "docker",
                        "container:env-lifecycle",
                        runtime_digest,
                        initial_materialization.materialization_digest,
                        scope,
                        profile.profile_id,
                        profile.profile_revision,
                    ),
                    role="runner",
                    scope=scope,
                )
            with self.assertRaises(RuntimeError):
                meta.environments.transition_profile_revision(
                    profile.profile_id,
                    profile.profile_revision,
                    EnvironmentProfileLifecycle.ACTIVE,
                )

            restored = build_platform_meta(root)
            restored_profile = restored.environments.profile_revision(
                profile.profile_id,
                profile.profile_revision,
            )
            self.assertIs(
                restored_profile.lifecycle,
                EnvironmentProfileLifecycle.RETIRED,
            )


    def test_durable_environment_hierarchy_survives_rebuild(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scope = ScopeIdentity(ScopeKind.WORKSPACE, "workspace")
            first = build_platform_meta(root)
            first.scopes.register(scope, PLATFORM_SCOPE)
            spec = EnvironmentSpec(
                "python-base", ExecutionEnvironmentKind.PYTHON, scope,
                requirements=(("python", "3.12"),),
                environment=(("PYTHONUNBUFFERED", "1"),),
            )
            first.environments.register_spec(spec)
            first.environments.assign(EnvironmentAssignment("default", "python-base", scope))
            revision = "2" * 64
            first.environments.register_profile_revision(
                EnvironmentProfileRevision(
                    "text-world-default",
                    "text_world",
                    revision,
                )
            )
            materialization = _register_materialization(
                first.environments,
                profile_id="text-world-default",
                profile_revision=revision,
                runtime_identity_digest="3" * 64,
                runtime_reference="python.exe",
            )
            instance = EnvironmentInstance(
                "env-1",
                "1" * 64,
                "local",
                "python.exe",
                "3" * 64,
                materialization.materialization_digest,
                scope,
                "text-world-default",
                revision,
            )
            first.environments.register_instance(instance)
            leased = first.environment_instance_leases.acquire_reusable_instance(
                "text-world-default",
                revision,
                "3" * 64,
                materialization.materialization_digest,
                binding_id="binding-1",
                role="runner",
                scope=scope,
            )
            binding = leased.binding
            second = build_platform_meta(root)
            resolved = second.environments.resolve("default", scope)
            self.assertEqual(resolved.requirements, (("python", "3.12"),))
            self.assertEqual(second.environments.binding("runner", scope), binding)
            self.assertEqual(
                second.environments.binding("runner", scope).instance_id,
                "env-1",
            )


def test_resource_lease_reconcile_can_be_scoped_to_one_resource_kind(tmp_path) -> None:
    from noetrium_platform.infrastructure.resources.lease.api import (
        ResourceIdentity,
        ResourceKind,
        ResourceLease,
        ResourceOwner,
    )
    from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE

    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=10.0,
    )
    registry = ResourceLeaseRegistry(
        tmp_path / "lease-kind.sqlite",
        clock=clock,
    )
    endpoint = ResourceIdentity(ResourceKind.NETWORK_ENDPOINT, "endpoint-a")
    container = ResourceIdentity(ResourceKind.CONTAINER, "container-a")
    for resource in (endpoint, container):
        registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
        registry.acquire(
            ResourceLease(
                f"lease:{resource.resource_id}",
                resource,
                PLATFORM_SCOPE,
                "kind-scoped-reconcile",
            ),
            ttl_seconds=1.0,
        )

    clock.advance(2.0)
    expired = registry.reconcile_expired(
        resource_kind=ResourceKind.CONTAINER,
    )
    assert [row.resource.kind for row in expired] == [ResourceKind.CONTAINER]
    endpoint_expired = registry.reconcile_expired(
        resource_kind=ResourceKind.NETWORK_ENDPOINT,
    )
    assert [row.resource.kind for row in endpoint_expired] == [
        ResourceKind.NETWORK_ENDPOINT
    ]
    assert registry.get("lease:container-a").state.value == "expired"
    assert registry.get("lease:endpoint-a").state.value == "expired"
