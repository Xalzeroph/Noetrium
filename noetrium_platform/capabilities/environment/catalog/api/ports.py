from __future__ import annotations

from typing import Protocol

from noetrium_platform.substrate.api import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import DurableCarrierReferenceClosure

from .contracts import (
    EnvironmentBinding,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceAcquisition,
    EnvironmentProfileGcAssessment,
    EnvironmentProfileLifecycle,
    EnvironmentProfileMaterialization,
    EnvironmentProfileReferenceSummary,
    EnvironmentProfileRevision,
    EnvironmentRuntimeGcAssessment,
    EnvironmentRuntimeReferenceSummary,
)


class ExecutionEnvironmentCatalogPort(Protocol):
    def register_profile_revision(
        self,
        profile: EnvironmentProfileRevision,
    ) -> None: ...
    def profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileRevision: ...
    def register_profile_materialization(
        self,
        materialization: EnvironmentProfileMaterialization,
    ) -> None: ...
    def profile_materialization(
        self,
        materialization_digest: str,
    ) -> EnvironmentProfileMaterialization: ...
    def profile_materializations(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> tuple[EnvironmentProfileMaterialization, ...]: ...
    def transition_profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
        lifecycle: EnvironmentProfileLifecycle,
    ) -> EnvironmentProfileRevision: ...
    def register_instance(self, instance: EnvironmentInstance) -> None: ...
    def instances(self) -> tuple[EnvironmentInstance, ...]: ...
    def bindings(self) -> tuple[EnvironmentBinding, ...]: ...
    def register_recovery_instance(
        self,
        instance: EnvironmentInstance,
        *,
        role: str,
        scope: NoetriumUnit,
    ) -> None: ...
    def bind(self, binding: EnvironmentBinding) -> None: ...
    def acquire_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        binding_id: str,
        role: str,
        scope: NoetriumUnit,
    ) -> EnvironmentInstanceAcquisition: ...
    def provision_reusable_instance(
        self,
        instance: EnvironmentInstance,
        *,
        binding_id: str,
        role: str,
        scope: NoetriumUnit,
    ) -> EnvironmentInstanceAcquisition: ...
    def recover_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        role: str,
        scope: NoetriumUnit,
    ) -> EnvironmentInstanceAcquisition: ...
    def unbind(self, role: str, scope: NoetriumUnit) -> EnvironmentBinding: ...
    def unbind_if_bound(
        self, role: str, scope: NoetriumUnit
    ) -> EnvironmentBinding | None: ...
    def binding(self, role: str, scope: NoetriumUnit) -> EnvironmentBinding: ...
    def release_instance(
        self,
        instance_id: str,
        *,
        cleanliness: EnvironmentCleanlinessProof | None = None,
    ) -> EnvironmentInstance: ...
    def mark_instance_dirty(self, instance_id: str) -> EnvironmentInstance: ...
    def destroy_instance(self, instance_id: str) -> EnvironmentInstance: ...
    def reusable_instances(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
    ) -> tuple[EnvironmentInstance, ...]: ...
    def profile_references(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileReferenceSummary: ...
    def assess_profile_gc(
        self,
        profile_id: str,
        profile_revision: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentProfileGcAssessment: ...
    def runtime_references(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
    ) -> EnvironmentRuntimeReferenceSummary: ...
    def assess_runtime_gc(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentRuntimeGcAssessment: ...


__all__ = ["ExecutionEnvironmentCatalogPort"]
