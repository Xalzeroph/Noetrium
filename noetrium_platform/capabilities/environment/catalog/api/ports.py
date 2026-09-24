from __future__ import annotations

from typing import Protocol

from noetrium_platform.substrate.api import ScopeIdentity

from .contracts import (
    EnvironmentAssignment,
    EnvironmentBinding,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentOverlay,
    EnvironmentProfileGcAssessment,
    EnvironmentProfileReferenceSummary,
    EnvironmentSpec,
    EnvironmentTemplate,
    ResolvedEnvironmentSpec,
)


class ExecutionEnvironmentCatalogPort(Protocol):
    def register_template(self, template: EnvironmentTemplate) -> None: ...
    def register_spec(self, spec: EnvironmentSpec) -> None: ...
    def register_overlay(self, overlay: EnvironmentOverlay) -> None: ...
    def assign(self, assignment: EnvironmentAssignment) -> None: ...
    def resolve(self, name: str, scope: ScopeIdentity) -> ResolvedEnvironmentSpec: ...
    def register_instance(self, instance: EnvironmentInstance) -> None: ...
    def bind(self, binding: EnvironmentBinding) -> None: ...
    def unbind(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding: ...
    def binding(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding: ...
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
        resumable_execution_ids: tuple[str, ...] | None = None,
        retained_evidence_ids: tuple[str, ...] | None = None,
    ) -> EnvironmentProfileGcAssessment: ...


__all__ = ["ExecutionEnvironmentCatalogPort"]
