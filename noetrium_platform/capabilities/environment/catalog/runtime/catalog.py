from __future__ import annotations

import heapq
import json
from dataclasses import replace
from pathlib import Path
import sqlite3
from typing import TypeVar

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
)
from noetrium_platform.foundation.kernel.kernel import DurableCarrierReferenceClosure, canonical_digest
from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline
from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentAssignment,
    EnvironmentBinding,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceAcquisition,
    EnvironmentInstanceState,
    EnvironmentOverlay,
    EnvironmentProfileGcAssessment,
    EnvironmentProfileLifecycle,
    EnvironmentProfileMaterialization,
    EnvironmentProfileReferenceSummary,
    EnvironmentProfileRevision,
    EnvironmentRuntimeGcAssessment,
    EnvironmentRuntimeReferenceSummary,
    EnvironmentSpec,
    EnvironmentTemplate,
    ExecutionEnvironmentKind,
    ResolvedEnvironmentSpec,
)
from noetrium_platform.substrate.api import (
    HierarchicalResourceResolver,
    ResolutionPolicy,
    ScopedValue,
)
from noetrium_platform.substrate.api import ScopeIdentity, ScopeKind, ScopeRegistryPort


_T = TypeVar("_T")


class EnvironmentCatalogConflict(RuntimeError):
    pass


class EnvironmentCatalogNotFound(KeyError):
    pass


class EnvironmentCatalogStaleRevision(RuntimeError):
    """Transient compare-and-swap conflict against durable catalog state."""


class ExecutionEnvironmentCatalog:
    """Hierarchy-aware logical environment authority.

    Logical specifications inherit through Scope System.  Physical Python/Conda/etc.
    environments remain separate instances and can be reused by many scoped bindings.
    """

    def __init__(self, scopes: ScopeRegistryPort) -> None:
        self._scopes = scopes
        self._profile_revisions: dict[
            tuple[str, str], EnvironmentProfileRevision
        ] = {}
        self._profile_materializations: dict[
            str, EnvironmentProfileMaterialization
        ] = {}
        self._templates: dict[str, EnvironmentTemplate] = {}
        self._specs: dict[str, EnvironmentSpec] = {}
        self._overlays: dict[str, EnvironmentOverlay] = {}
        self._assignments = HierarchicalResourceResolver[str](ancestry=scopes.ancestry)
        self._instances: dict[str, EnvironmentInstance] = {}
        self._binding_rows: dict[tuple[str, str], EnvironmentBinding] = {}
        self._bindings = HierarchicalResourceResolver[EnvironmentBinding](ancestry=scopes.ancestry)
        self._clean_instance_ids: dict[tuple[str, str, str, str], set[str]] = {}
        self._clean_instance_heaps: dict[tuple[str, str, str, str], list[str]] = {}
        self._binding_keys_by_instance: dict[str, set[tuple[str, str]]] = {}

    @staticmethod
    def _put(store: dict[str, _T], key: str, value: _T) -> None:
        current = store.get(key)
        if current is not None and current != value:
            raise EnvironmentCatalogConflict(key)
        store[key] = value

    def register_profile_revision(
        self,
        profile: EnvironmentProfileRevision,
    ) -> None:
        if type(profile) is not EnvironmentProfileRevision:
            raise TypeError(
                "environment profile registration requires EnvironmentProfileRevision"
            )
        key = (profile.profile_id, profile.profile_revision)
        current = self._profile_revisions.get(key)
        if current is not None and current != profile:
            raise EnvironmentCatalogConflict(
                f"environment profile revision already registered: {key!r}"
            )
        self._profile_revisions[key] = profile

    def _profile_revision_local(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileRevision:
        try:
            return self._profile_revisions[(profile_id, profile_revision)]
        except KeyError as exc:
            raise EnvironmentCatalogNotFound(
                ("profile-revision", profile_id, profile_revision)
            ) from exc

    def profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileRevision:
        return self._profile_revision_local(profile_id, profile_revision)

    def register_profile_materialization(
        self,
        materialization: EnvironmentProfileMaterialization,
    ) -> None:
        if type(materialization) is not EnvironmentProfileMaterialization:
            raise TypeError(
                "environment materialization registration requires "
                "EnvironmentProfileMaterialization"
            )
        self._profile_revision_local(
            materialization.profile_id,
            materialization.profile_revision,
        )
        self._put(
            self._profile_materializations,
            materialization.materialization_digest,
            materialization,
        )

    def _profile_materialization_local(
        self,
        materialization_digest: str,
    ) -> EnvironmentProfileMaterialization:
        try:
            return self._profile_materializations[materialization_digest]
        except KeyError as exc:
            raise EnvironmentCatalogNotFound(
                ("profile-materialization", materialization_digest)
            ) from exc

    def profile_materialization(
        self,
        materialization_digest: str,
    ) -> EnvironmentProfileMaterialization:
        return self._profile_materialization_local(materialization_digest)

    def profile_materializations(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> tuple[EnvironmentProfileMaterialization, ...]:
        self._profile_revision_local(profile_id, profile_revision)
        return tuple(
            sorted(
                (
                    row
                    for row in self._profile_materializations.values()
                    if row.profile_id == profile_id
                    and row.profile_revision == profile_revision
                ),
                key=lambda row: row.materialization_digest,
            )
        )

    def transition_profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
        lifecycle: EnvironmentProfileLifecycle,
    ) -> EnvironmentProfileRevision:
        if type(lifecycle) is not EnvironmentProfileLifecycle:
            raise TypeError(
                "environment profile transition requires EnvironmentProfileLifecycle"
            )
        current = self._profile_revision_local(profile_id, profile_revision)
        if current.lifecycle is lifecycle:
            return current
        allowed = {
            EnvironmentProfileLifecycle.ACTIVE: EnvironmentProfileLifecycle.DRAINING,
            EnvironmentProfileLifecycle.DRAINING: EnvironmentProfileLifecycle.RETIRED,
        }
        if allowed.get(current.lifecycle) is not lifecycle:
            raise EnvironmentCatalogConflict(
                "environment profile lifecycle is monotonic: "
                f"{current.lifecycle.value} -> {lifecycle.value} is forbidden"
            )
        if lifecycle is EnvironmentProfileLifecycle.RETIRED:
            in_use = tuple(
                sorted(
                    row.instance_id
                    for row in self._instances.values()
                    if row.profile_id == profile_id
                    and row.profile_revision == profile_revision
                    and row.state is EnvironmentInstanceState.IN_USE
                )
            )
            if in_use:
                raise EnvironmentCatalogConflict(
                    "environment profile cannot retire with in-use instances: "
                    + ",".join(in_use)
                )
        updated = replace(current, lifecycle=lifecycle)
        self._profile_revisions[(profile_id, profile_revision)] = updated
        return updated

    def _require_new_profile_admission(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileRevision:
        profile = self._profile_revision_local(profile_id, profile_revision)
        if profile.lifecycle is not EnvironmentProfileLifecycle.ACTIVE:
            raise EnvironmentCatalogConflict(
                "environment profile revision does not admit new work: "
                f"{profile.profile_id}@{profile.profile_revision} "
                f"state={profile.lifecycle.value}"
            )
        return profile

    def _require_recovery_pin(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> tuple[EnvironmentBinding, EnvironmentInstance]:
        profile = self._profile_revision_local(profile_id, profile_revision)
        if profile.lifecycle is EnvironmentProfileLifecycle.RETIRED:
            raise EnvironmentCatalogConflict(
                "retired environment profile revisions cannot enter live execution"
            )
        key = (role, scope.key)
        try:
            binding = self._binding_rows[key]
        except KeyError as exc:
            raise EnvironmentCatalogConflict(
                "environment recovery requires an existing durable binding pin"
            ) from exc
        pinned = self._instance(binding.instance_id)
        if (
            pinned.profile_id != profile_id
            or pinned.profile_revision != profile_revision
            or pinned.runtime_identity_digest != runtime_identity_digest
            or pinned.materialization_digest != materialization_digest
        ):
            raise EnvironmentCatalogConflict(
                "environment recovery request does not match the durable binding pin"
            )
        if pinned.state is not EnvironmentInstanceState.IN_USE:
            raise EnvironmentCatalogConflict(
                "environment recovery binding does not reference an in-use instance"
            )
        return binding, pinned

    def _validate_instance_materialization(
        self,
        instance: EnvironmentInstance,
    ) -> EnvironmentProfileMaterialization:
        materialization = self._profile_materialization_local(
            instance.materialization_digest
        )
        expected = (
            materialization.profile_id,
            materialization.profile_revision,
            materialization.runtime_identity_digest,
            materialization.runtime_reference,
        )
        actual = (
            instance.profile_id,
            instance.profile_revision,
            instance.runtime_identity_digest,
            instance.runtime_reference,
        )
        if actual != expected:
            raise EnvironmentCatalogConflict(
                "environment instance drifted from verified materialization"
            )
        return materialization

    @staticmethod
    def _validate_fresh_instance(instance: EnvironmentInstance) -> None:
        if instance.state is not EnvironmentInstanceState.CLEAN:
            raise EnvironmentCatalogConflict(
                "new environment instance must enter catalog CLEAN"
            )
        if instance.generation != 0:
            raise EnvironmentCatalogConflict(
                "new environment instance generation must start at zero"
            )

    def register_template(self, template: EnvironmentTemplate) -> None:
        self._put(self._templates, template.template_id, template)

    def register_spec(self, spec: EnvironmentSpec) -> None:
        if spec.parent_spec_id is not None and spec.parent_spec_id not in self._specs:
            raise EnvironmentCatalogNotFound(spec.parent_spec_id)
        if spec.template_id is not None and spec.template_id not in self._templates:
            raise EnvironmentCatalogNotFound(spec.template_id)
        self._put(self._specs, spec.spec_id, spec)

    def register_overlay(self, overlay: EnvironmentOverlay) -> None:
        if overlay.target_spec_id not in self._specs:
            raise EnvironmentCatalogNotFound(overlay.target_spec_id)
        self._put(self._overlays, overlay.overlay_id, overlay)

    def assign(self, assignment: EnvironmentAssignment) -> None:
        if assignment.spec_id not in self._specs:
            raise EnvironmentCatalogNotFound(assignment.spec_id)
        self._assignments.bind(ScopedValue("execution-environment", assignment.name, assignment.scope, assignment.spec_id, assignment.policy))

    def _spec_chain(self, spec: EnvironmentSpec) -> tuple[EnvironmentSpec, ...]:
        chain = [spec]
        seen = {spec.spec_id}
        current = spec
        while current.parent_spec_id is not None:
            try:
                current = self._specs[current.parent_spec_id]
            except KeyError as exc:
                raise EnvironmentCatalogNotFound(current.parent_spec_id) from exc
            if current.spec_id in seen:
                raise EnvironmentCatalogConflict(f"environment spec cycle: {current.spec_id}")
            seen.add(current.spec_id)
            chain.append(current)
        chain.reverse()
        return tuple(chain)

    def resolve(self, name: str, scope: ScopeIdentity) -> ResolvedEnvironmentSpec:
        assigned = self._assignments.resolve(namespace="execution-environment", name=name, scope=scope)
        try:
            leaf = self._specs[assigned.value]
        except KeyError as exc:
            raise EnvironmentCatalogNotFound(assigned.value) from exc
        chain = self._spec_chain(leaf)
        requirements: dict[str, str] = {}
        environment: dict[str, str] = {}
        source_scopes: list[ScopeIdentity] = []
        for spec in chain:
            requirements.update(spec.requirements)
            environment.update(spec.environment)
            source_scopes.append(spec.scope)
        ancestry_path = self._scopes.ancestry(scope)
        ancestry_rank = {identity: index for index, identity in enumerate(ancestry_path)}
        chain_ids = {item.spec_id for item in chain}
        overlays = tuple(sorted(
            (
                row for row in self._overlays.values()
                if row.target_spec_id in chain_ids and row.scope in ancestry_rank
            ),
            key=lambda row: ancestry_rank[row.scope],
            reverse=True,
        ))
        for overlay in overlays:
            requirements.update(overlay.requirements)
            environment.update(overlay.environment)
            source_scopes.append(overlay.scope)
        return ResolvedEnvironmentSpec(
            spec_id=leaf.spec_id,
            kind=leaf.kind,
            requested_scope=scope,
            source_scopes=tuple(source_scopes),
            source_spec_ids=tuple(item.spec_id for item in chain),
            applied_overlay_ids=tuple(item.overlay_id for item in overlays),
            requirements=tuple(sorted(requirements.items())),
            environment=tuple(sorted(environment.items())),
        )

    @staticmethod
    def _reuse_key(instance: EnvironmentInstance) -> tuple[str, str, str, str]:
        return (
            instance.profile_id,
            instance.profile_revision,
            instance.runtime_identity_digest,
            instance.materialization_digest,
        )

    def _add_clean_instance(self, instance: EnvironmentInstance) -> None:
        if instance.state is not EnvironmentInstanceState.CLEAN:
            return
        key = self._reuse_key(instance)
        active = self._clean_instance_ids.setdefault(key, set())
        if instance.instance_id in active:
            return
        active.add(instance.instance_id)
        heapq.heappush(self._clean_instance_heaps.setdefault(key, []), instance.instance_id)

    def _remove_clean_instance(self, instance: EnvironmentInstance) -> None:
        key = self._reuse_key(instance)
        active = self._clean_instance_ids.get(key)
        if active is None:
            return
        active.discard(instance.instance_id)
        if not active:
            self._clean_instance_ids.pop(key, None)

    def _set_instance(self, instance: EnvironmentInstance) -> None:
        current = self._instances.get(instance.instance_id)
        if current == instance:
            return
        if current is not None and current.state is EnvironmentInstanceState.CLEAN:
            self._remove_clean_instance(current)
        self._instances[instance.instance_id] = instance
        self._add_clean_instance(instance)

    def _put_instance(self, instance: EnvironmentInstance) -> None:
        current = self._instances.get(instance.instance_id)
        if current is not None:
            if current != instance:
                raise EnvironmentCatalogConflict(instance.instance_id)
            return
        self._set_instance(instance)

    def _next_clean_instance(
        self,
        key: tuple[str, str, str, str],
    ) -> EnvironmentInstance | None:
        active = self._clean_instance_ids.get(key)
        heap = self._clean_instance_heaps.get(key)
        if not active or not heap:
            return None
        while heap and heap[0] not in active:
            heapq.heappop(heap)
        if not heap:
            self._clean_instance_heaps.pop(key, None)
            return None
        return self._instances[heap[0]]

    def _rebuild_clean_instance_index(self) -> None:
        self._clean_instance_ids = {}
        self._clean_instance_heaps = {}
        for instance in self._instances.values():
            self._add_clean_instance(instance)

    def register_instance(self, instance: EnvironmentInstance) -> None:
        self._require_new_profile_admission(
            instance.profile_id,
            instance.profile_revision,
        )
        self._validate_instance_materialization(instance)
        self._validate_fresh_instance(instance)
        self._put_instance(instance)

    def instances(self) -> tuple[EnvironmentInstance, ...]:
        return tuple(sorted(self._instances.values(), key=lambda row: row.instance_id))

    def bindings(self) -> tuple[EnvironmentBinding, ...]:
        return tuple(
            sorted(
                self._binding_rows.values(),
                key=lambda row: (row.scope.key, row.role, row.binding_id),
            )
        )

    def register_recovery_instance(
        self,
        instance: EnvironmentInstance,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> None:
        _binding, pinned = self._require_recovery_pin(
            instance.profile_id,
            instance.profile_revision,
            instance.runtime_identity_digest,
            instance.materialization_digest,
            role=role,
            scope=scope,
        )
        if instance.scope != scope:
            raise EnvironmentCatalogConflict(
                "recovery instance scope must match the pinned execution scope"
            )
        if instance.instance_id == pinned.instance_id:
            raise EnvironmentCatalogConflict(
                "recovery instance must be a distinct replacement instance"
            )
        self._validate_instance_materialization(instance)
        self._validate_fresh_instance(instance)
        self._put_instance(instance)

    def _rebuild_bindings(self) -> None:
        self._bindings = HierarchicalResourceResolver[EnvironmentBinding](
            ancestry=self._scopes.ancestry
        )
        self._binding_keys_by_instance = {}
        for row in self._binding_rows.values():
            self._bindings.bind(
                ScopedValue(
                    "execution-environment-instance",
                    row.role,
                    row.scope,
                    row,
                )
            )
            self._binding_keys_by_instance.setdefault(row.instance_id, set()).add(
                (row.role, row.scope.key)
            )

    def _instance(self, instance_id: str) -> EnvironmentInstance:
        try:
            return self._instances[instance_id]
        except KeyError as exc:
            raise EnvironmentCatalogNotFound(instance_id) from exc

    def _bindings_for_instance(
        self,
        instance_id: str,
    ) -> tuple[EnvironmentBinding, ...]:
        keys = self._binding_keys_by_instance.get(instance_id, ())
        return tuple(
            sorted(
                (
                    self._binding_rows[key]
                    for key in keys
                    if key in self._binding_rows
                ),
                key=lambda row: (row.scope.key, row.role, row.binding_id),
            )
        )

    def bind(self, binding: EnvironmentBinding) -> None:
        instance = self._instance(binding.instance_id)
        key = (binding.role, binding.scope.key)
        existing = self._binding_rows.get(key)
        if existing is not None:
            if existing != binding:
                raise EnvironmentCatalogConflict(
                    f"environment binding already exists for {key!r}"
                )
            return

        existing_bindings = self._bindings_for_instance(binding.instance_id)
        if instance.state is EnvironmentInstanceState.CLEAN:
            self._require_new_profile_admission(
                instance.profile_id,
                instance.profile_revision,
            )
            next_instance = replace(
                instance,
                state=EnvironmentInstanceState.IN_USE,
                generation=instance.generation + 1,
                cleanliness_proof_digest=None,
            )
        elif instance.state is EnvironmentInstanceState.IN_USE:
            scopes = {row.scope.key for row in existing_bindings}
            if not scopes or scopes != {binding.scope.key}:
                raise EnvironmentCatalogConflict(
                    "in-use environment instance can only extend its pinned scope"
                )
            next_instance = instance
        else:
            raise EnvironmentCatalogConflict(
                f"environment instance {binding.instance_id!r} is not reusable: "
                f"state={instance.state.value}"
            )

        self._bindings.bind(
            ScopedValue(
                "execution-environment-instance",
                binding.role,
                binding.scope,
                binding,
            )
        )
        self._binding_rows[key] = binding
        self._binding_keys_by_instance.setdefault(binding.instance_id, set()).add(key)
        self._set_instance(next_instance)

    def acquire_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        binding_id: str,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceAcquisition:
        """Atomically acquire one CLEAN ACTIVE revision for new work."""

        for field_name, value in (
            ("profile_id", profile_id),
            ("binding_id", binding_id),
            ("role", role),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"environment reusable acquisition {field_name} "
                    "must be canonical non-empty text"
                )
        for field_name, value in (
            ("profile_revision", profile_revision),
            ("runtime_identity_digest", runtime_identity_digest),
            ("materialization_digest", materialization_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"environment reusable acquisition {field_name} "
                    "must be lowercase sha256"
                )
        if type(scope) is not ScopeIdentity:
            raise TypeError(
                "environment reusable acquisition scope must be ScopeIdentity"
            )
        self._require_new_profile_admission(profile_id, profile_revision)

        candidate = self._next_clean_instance(
            (
                profile_id,
                profile_revision,
                runtime_identity_digest,
                materialization_digest,
            )
        )
        if candidate is None:
            raise EnvironmentCatalogNotFound(
                (
                    "reusable",
                    profile_id,
                    profile_revision,
                    runtime_identity_digest,
                    materialization_digest,
                )
            )

        binding = EnvironmentBinding(
            binding_id,
            scope,
            role,
            candidate.instance_id,
        )
        ExecutionEnvironmentCatalog.bind(self, binding)
        acquired = self._instance(candidate.instance_id)
        return EnvironmentInstanceAcquisition(binding, acquired)

    def recover_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceAcquisition:
        """Atomically replace an already-pinned ACTIVE/DRAINING instance."""

        pinned_binding, pinned_instance = self._require_recovery_pin(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization_digest,
            role=role,
            scope=scope,
        )
        related_bindings = self._bindings_for_instance(pinned_instance.instance_id)
        if not related_bindings:
            raise EnvironmentCatalogConflict(
                "environment recovery pin lost its binding set"
            )
        if {row.scope.key for row in related_bindings} != {scope.key}:
            raise EnvironmentCatalogConflict(
                "environment recovery cannot migrate bindings across scopes"
            )

        replacement = self._next_clean_instance(
            (
                profile_id,
                profile_revision,
                runtime_identity_digest,
                materialization_digest,
            )
        )
        if replacement is None:
            raise EnvironmentCatalogNotFound(
                (
                    "recovery-replacement",
                    profile_id,
                    profile_revision,
                    runtime_identity_digest,
                    materialization_digest,
                )
            )
        if replacement.scope != scope:
            raise EnvironmentCatalogConflict(
                "environment recovery replacement scope differs from pinned scope"
            )

        replacement = replace(
            replacement,
            state=EnvironmentInstanceState.IN_USE,
            generation=replacement.generation + 1,
            cleanliness_proof_digest=None,
        )
        self._set_instance(replacement)
        self._set_instance(replace(
            pinned_instance,
            state=EnvironmentInstanceState.DIRTY,
            cleanliness_proof_digest=None,
        ))

        migrated: dict[str, EnvironmentBinding] = {}
        for old in related_bindings:
            new = EnvironmentBinding(
                old.binding_id,
                old.scope,
                old.role,
                replacement.instance_id,
            )
            self._binding_rows[(old.role, old.scope.key)] = new
            migrated[old.role] = new
        self._rebuild_bindings()
        return EnvironmentInstanceAcquisition(
            migrated[pinned_binding.role],
            replacement,
        )

    def unbind(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding:
        key = (role, scope.key)
        try:
            binding = self._binding_rows.pop(key)
        except KeyError as exc:
            raise EnvironmentCatalogNotFound(key) from exc
        self._rebuild_bindings()
        return binding

    def binding(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding:
        return self._bindings.resolve(
            namespace="execution-environment-instance",
            name=role,
            scope=scope,
        ).value

    def release_instance(
        self,
        instance_id: str,
        *,
        cleanliness: EnvironmentCleanlinessProof | None = None,
    ) -> EnvironmentInstance:
        instance = self._instance(instance_id)
        bound = self._bindings_for_instance(instance_id)
        if bound:
            raise EnvironmentCatalogConflict(
                f"environment instance {instance_id!r} still has active bindings"
            )
        if instance.state is EnvironmentInstanceState.DESTROYED:
            raise EnvironmentCatalogConflict(
                f"environment instance {instance_id!r} is already destroyed"
            )
        if instance.state is EnvironmentInstanceState.CLEAN:
            if cleanliness is not None:
                raise EnvironmentCatalogConflict(
                    "fresh CLEAN environment instance does not accept a reuse proof"
                )
            return instance
        if cleanliness is not None and type(cleanliness) is not EnvironmentCleanlinessProof:
            raise TypeError(
                "environment release cleanliness must be EnvironmentCleanlinessProof"
            )
        if cleanliness is None:
            updated = replace(
                instance,
                state=EnvironmentInstanceState.DIRTY,
                cleanliness_proof_digest=None,
            )
            self._instances[instance_id] = updated
            return updated

        if cleanliness.instance_id != instance_id:
            raise EnvironmentCatalogConflict(
                "environment cleanliness proof targets a different instance"
            )
        if cleanliness.profile_revision != instance.profile_revision:
            raise EnvironmentCatalogConflict(
                "environment cleanliness proof profile revision is stale"
            )
        if cleanliness.runtime_identity_digest != instance.runtime_identity_digest:
            raise EnvironmentCatalogConflict(
                "environment cleanliness proof runtime identity is stale"
            )
        if cleanliness.materialization_digest != instance.materialization_digest:
            raise EnvironmentCatalogConflict(
                "environment cleanliness proof materialization identity is stale"
            )
        if cleanliness.generation != instance.generation:
            raise EnvironmentCatalogConflict(
                "environment cleanliness proof generation is stale"
            )
        updated = replace(
            instance,
            state=EnvironmentInstanceState.CLEAN,
            cleanliness_proof_digest=cleanliness.proof_digest,
        )
        self._set_instance(updated)
        return updated

    def mark_instance_dirty(self, instance_id: str) -> EnvironmentInstance:
        instance = self._instance(instance_id)
        if instance.state is EnvironmentInstanceState.DESTROYED:
            raise EnvironmentCatalogConflict(
                f"destroyed environment instance {instance_id!r} cannot become dirty"
            )
        updated = replace(
            instance,
            state=EnvironmentInstanceState.DIRTY,
            cleanliness_proof_digest=None,
        )
        self._set_instance(updated)
        return updated

    def destroy_instance(self, instance_id: str) -> EnvironmentInstance:
        instance = self._instance(instance_id)
        if self._bindings_for_instance(instance_id):
            raise EnvironmentCatalogConflict(
                f"environment instance {instance_id!r} still has active bindings"
            )
        if instance.state is EnvironmentInstanceState.DESTROYED:
            return instance
        updated = replace(
            instance,
            state=EnvironmentInstanceState.DESTROYED,
            cleanliness_proof_digest=None,
        )
        self._set_instance(updated)
        return updated

    def reusable_instances(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
    ) -> tuple[EnvironmentInstance, ...]:
        key = (
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization_digest,
        )
        active = self._clean_instance_ids.get(key, ())
        return tuple(
            self._instances[instance_id]
            for instance_id in sorted(active)
        )

    def _profile_references_local(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileReferenceSummary:
        matching = tuple(
            sorted(
                (
                    row
                    for row in self._instances.values()
                    if row.profile_id == profile_id
                    and row.profile_revision == profile_revision
                ),
                key=lambda row: row.instance_id,
            )
        )
        matching_ids = {row.instance_id for row in matching}
        bound_ids = tuple(
            sorted(
                {
                    row.instance_id
                    for row in self._binding_rows.values()
                    if row.instance_id in matching_ids
                }
            )
        )
        reusable_ids = tuple(
            row.instance_id
            for row in matching
            if row.state is EnvironmentInstanceState.CLEAN
        )
        blocking_ids = tuple(
            row.instance_id
            for row in matching
            if row.state is not EnvironmentInstanceState.DESTROYED
        )
        return EnvironmentProfileReferenceSummary(
            profile_id,
            profile_revision,
            tuple(row.instance_id for row in matching),
            bound_ids,
            reusable_ids,
            blocking_ids,
        )

    def profile_references(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileReferenceSummary:
        return self._profile_references_local(profile_id, profile_revision)

    def assess_profile_gc(
        self,
        profile_id: str,
        profile_revision: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentProfileGcAssessment:
        return EnvironmentProfileGcAssessment(
            profile_id,
            profile_revision,
            self._profile_references_local(profile_id, profile_revision),
            closures,
        )

    def _runtime_references_local(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
    ) -> EnvironmentRuntimeReferenceSummary:
        matching = tuple(
            sorted(
                (
                    row
                    for row in self._instances.values()
                    if row.profile_id == profile_id
                    and row.profile_revision == profile_revision
                    and row.runtime_identity_digest == runtime_identity_digest
                ),
                key=lambda row: row.instance_id,
            )
        )
        matching_ids = {row.instance_id for row in matching}
        bound_ids = tuple(
            sorted(
                {
                    row.instance_id
                    for row in self._binding_rows.values()
                    if row.instance_id in matching_ids
                }
            )
        )
        reusable_ids = tuple(
            row.instance_id
            for row in matching
            if row.state is EnvironmentInstanceState.CLEAN
        )
        blocking_ids = tuple(
            row.instance_id
            for row in matching
            if row.state is not EnvironmentInstanceState.DESTROYED
        )
        return EnvironmentRuntimeReferenceSummary(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            tuple(row.instance_id for row in matching),
            bound_ids,
            reusable_ids,
            blocking_ids,
        )

    def runtime_references(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
    ) -> EnvironmentRuntimeReferenceSummary:
        return self._runtime_references_local(
            profile_id,
            profile_revision,
            runtime_identity_digest,
        )

    def assess_runtime_gc(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentRuntimeGcAssessment:
        return EnvironmentRuntimeGcAssessment(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            self._runtime_references_local(
                profile_id,
                profile_revision,
                runtime_identity_digest,
            ),
            closures,
        )

    @staticmethod
    def resolved_digest(value: ResolvedEnvironmentSpec) -> str:
        return canonical_digest(value)


__all__ = ["EnvironmentCatalogConflict", "EnvironmentCatalogNotFound", "ExecutionEnvironmentCatalog"]

_MISSING = object()


class _TrackedDict(dict):
    """Derived dirty-key projection for incremental catalog persistence."""

    __slots__ = ("dirty_keys", "deleted_keys")

    def __init__(self, values=()) -> None:
        super().__init__(values)
        self.dirty_keys: set[object] = set()
        self.deleted_keys: set[object] = set()

    def __setitem__(self, key, value) -> None:
        previous = self.get(key, _MISSING)
        super().__setitem__(key, value)
        if previous is _MISSING or previous != value:
            self.dirty_keys.add(key)
            self.deleted_keys.discard(key)

    def pop(self, key, *default):
        existed = key in self
        value = super().pop(key, *default)
        if existed:
            self.dirty_keys.discard(key)
            self.deleted_keys.add(key)
        return value

    def load_set(self, key, value) -> None:
        dict.__setitem__(self, key, value)

    def load_pop(self, key) -> None:
        dict.pop(self, key, None)

    def clear_changes(self) -> None:
        self.dirty_keys.clear()
        self.deleted_keys.clear()


class SQLiteExecutionEnvironmentCatalog(ExecutionEnvironmentCatalog):
    """Restart-safe environment hierarchy and binding authority."""

    SCHEMA_VERSION = 7
    CHECKPOINT_INTERVAL = 512

    def __init__(
        self, path: str | Path, scopes: ScopeRegistryPort, *,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(scopes)
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        self._writers = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
        self._assignment_rows: dict[tuple[str, str], EnvironmentAssignment] = {}
        self._state_generation = 0
        self._checkpoint_generation = 0
        self._loaded = False
        with self._connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS environment_state("
                "state_id INTEGER PRIMARY KEY CHECK(state_id=1),"
                "schema_version INTEGER NOT NULL, generation INTEGER NOT NULL,"
                "checkpoint_generation INTEGER NOT NULL DEFAULT 0,"
                "payload TEXT NOT NULL)"
            )
            columns = {
                str(row[1])
                for row in conn.execute(
                    "PRAGMA table_info(environment_state)"
                ).fetchall()
            }
            if "checkpoint_generation" not in columns:
                conn.execute(
                    "ALTER TABLE environment_state "
                    "ADD COLUMN checkpoint_generation INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS environment_events("
                "generation INTEGER PRIMARY KEY,"
                "event_digest TEXT NOT NULL,"
                "payload TEXT NOT NULL)"
            )
            row = conn.execute(
                "SELECT schema_version,generation "
                "FROM environment_state WHERE state_id=1"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO environment_state("
                    "state_id,schema_version,generation,checkpoint_generation,payload)"
                    " VALUES(1,?,?,?,?)",
                    (self.SCHEMA_VERSION, 0, 0, "{}"),
                )
            else:
                schema_version = int(row[0])
                generation = int(row[1])
                if schema_version == 6:
                    # One-time format migration: the v6 payload is already a
                    # complete authoritative checkpoint at its generation.
                    conn.execute(
                        "UPDATE environment_state SET "
                        "schema_version=?, checkpoint_generation=generation "
                        "WHERE state_id=1",
                        (self.SCHEMA_VERSION,),
                    )
                    conn.execute("DELETE FROM environment_events")
                elif schema_version != self.SCHEMA_VERSION:
                    raise RuntimeError(
                        "unsupported SQLiteExecutionEnvironmentCatalog schema"
                    )
        self._load()

    def _connection(self):
        return self._writers.session()

    @property
    def writer_connection_open_count(self) -> int:
        return self._writers.open_count

    def close(self) -> None:
        self._writers.close()

    @staticmethod
    def _scope(value: ScopeIdentity) -> dict[str, str]:
        return {"kind": value.kind.value, "scope_id": value.scope_id}

    @staticmethod
    def _decode_scope(value: dict[str, str]) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind(value["kind"]), value["scope_id"])

    @classmethod
    def _pairs(cls, value: tuple[tuple[str, str], ...]) -> list[list[str]]:
        return [list(row) for row in value]

    @classmethod
    def _profile_revision(
        cls,
        value: EnvironmentProfileRevision,
    ) -> dict[str, object]:
        return {
            "profile_id": value.profile_id,
            "category_id": value.category_id,
            "profile_revision": value.profile_revision,
            "lifecycle": value.lifecycle.value,
        }

    @classmethod
    def _profile_materialization(
        cls,
        value: EnvironmentProfileMaterialization,
    ) -> dict[str, object]:
        return {
            "profile_id": value.profile_id,
            "profile_revision": value.profile_revision,
            "build_input_digest": value.build_input_digest,
            "runtime_identity_digest": value.runtime_identity_digest,
            "deployment_receipt_digest": value.deployment_receipt_digest,
            "runtime_reference": value.runtime_reference,
            "materialization_digest": value.materialization_digest,
        }

    @classmethod
    def _template(cls, value: EnvironmentTemplate) -> dict[str, object]:
        return {
            "template_id": value.template_id, "kind": value.kind.value,
            "scope": cls._scope(value.scope), "base_spec_id": value.base_spec_id,
            "description": value.description,
        }

    @classmethod
    def _spec(cls, value: EnvironmentSpec) -> dict[str, object]:
        return {
            "spec_id": value.spec_id, "kind": value.kind.value,
            "scope": cls._scope(value.scope), "parent_spec_id": value.parent_spec_id,
            "template_id": value.template_id, "requirements": cls._pairs(value.requirements),
            "environment": cls._pairs(value.environment), "tags": list(value.tags),
        }

    @classmethod
    def _overlay(cls, value: EnvironmentOverlay) -> dict[str, object]:
        return {
            "overlay_id": value.overlay_id, "target_spec_id": value.target_spec_id,
            "scope": cls._scope(value.scope), "requirements": cls._pairs(value.requirements),
            "environment": cls._pairs(value.environment),
        }

    @classmethod
    def _assignment(cls, value: EnvironmentAssignment) -> dict[str, object]:
        return {
            "name": value.name, "spec_id": value.spec_id,
            "scope": cls._scope(value.scope), "policy": value.policy.value,
        }

    @classmethod
    def _instance_payload(cls, value: EnvironmentInstance) -> dict[str, object]:
        return {
            "instance_id": value.instance_id,
            "resolved_spec_digest": value.resolved_spec_digest,
            "backend": value.backend,
            "runtime_reference": value.runtime_reference,
            "runtime_identity_digest": value.runtime_identity_digest,
            "materialization_digest": value.materialization_digest,
            "scope": cls._scope(value.scope),
            "profile_id": value.profile_id,
            "profile_revision": value.profile_revision,
            "state": value.state.value,
            "generation": value.generation,
            "cleanliness_proof_digest": value.cleanliness_proof_digest,
        }

    @classmethod
    def _binding(cls, value: EnvironmentBinding) -> dict[str, object]:
        return {
            "binding_id": value.binding_id, "scope": cls._scope(value.scope),
            "role": value.role, "instance_id": value.instance_id,
        }

    def _state(self) -> str:
        return json.dumps({
            "profile_revisions": [
                self._profile_revision(row)
                for row in self._profile_revisions.values()
            ],
            "profile_materializations": [
                self._profile_materialization(row)
                for row in self._profile_materializations.values()
            ],
            "templates": [self._template(row) for row in self._templates.values()],
            "specs": [self._spec(row) for row in self._specs.values()],
            "overlays": [self._overlay(row) for row in self._overlays.values()],
            "assignments": [self._assignment(row) for row in self._assignment_rows.values()],
            "instances": [
                self._instance_payload(row)
                for row in self._instances.values()
            ],
            "bindings": [self._binding(row) for row in self._binding_rows.values()],
        }, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _tracked_values(store: _TrackedDict, serializer) -> list[object]:
        return [
            serializer(store[key])
            for key in sorted(store.dirty_keys, key=repr)
            if key in store
        ]

    def _event_payload(self) -> dict[str, object] | None:
        stores = (
            self._profile_revisions,
            self._profile_materializations,
            self._templates,
            self._specs,
            self._overlays,
            self._assignment_rows,
            self._instances,
            self._binding_rows,
        )
        if not any(
            isinstance(store, _TrackedDict)
            and (store.dirty_keys or store.deleted_keys)
            for store in stores
        ):
            return None
        bindings = self._binding_rows
        if not isinstance(bindings, _TrackedDict):
            raise RuntimeError("environment binding projection is not tracked")
        return {
            "schema": "noetrium.environment-catalog-event.v1",
            "profile_revisions": self._tracked_values(
                self._profile_revisions, self._profile_revision
            ),
            "profile_materializations": self._tracked_values(
                self._profile_materializations, self._profile_materialization
            ),
            "templates": self._tracked_values(
                self._templates, self._template
            ),
            "specs": self._tracked_values(
                self._specs, self._spec
            ),
            "overlays": self._tracked_values(
                self._overlays, self._overlay
            ),
            "assignments": self._tracked_values(
                self._assignment_rows, self._assignment
            ),
            "instances": self._tracked_values(
                self._instances, self._instance_payload
            ),
            "bindings": self._tracked_values(
                bindings, self._binding
            ),
            "deleted_bindings": [
                [str(key[0]), str(key[1])]
                for key in sorted(bindings.deleted_keys, key=repr)
            ],
        }

    def _clear_changes(self) -> None:
        for store in (
            self._profile_revisions,
            self._profile_materializations,
            self._templates,
            self._specs,
            self._overlays,
            self._assignment_rows,
            self._instances,
            self._binding_rows,
        ):
            if isinstance(store, _TrackedDict):
                store.clear_changes()

    def _persist(self) -> None:
        event = self._event_payload()
        if event is None:
            return
        encoded_event = json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
        )
        event_digest = canonical_digest(event)
        try:
            with self._connection() as conn:
                with immediate_sqlite_transaction(
                    conn,
                    timeout_seconds=self.timeout_seconds,
                    label="environment catalog",
                ):
                    row = conn.execute(
                        "SELECT schema_version,generation,checkpoint_generation "
                        "FROM environment_state WHERE state_id=1"
                    ).fetchone()
                    if row is None or int(row[0]) != self.SCHEMA_VERSION:
                        raise RuntimeError(
                            "unsupported SQLiteExecutionEnvironmentCatalog schema"
                        )
                    durable_generation = int(row[1])
                    checkpoint_generation = int(row[2])
                    if durable_generation != self._state_generation:
                        self._loaded = False
                        raise EnvironmentCatalogStaleRevision(
                            "stale environment catalog revision; reload and retry"
                        )
                    next_generation = durable_generation + 1
                    checkpoint_due = (
                        next_generation - checkpoint_generation
                        >= self.CHECKPOINT_INTERVAL
                    )
                    if checkpoint_due:
                        payload = self._state()
                        updated = conn.execute(
                            "UPDATE environment_state SET "
                            "generation=?, checkpoint_generation=?, payload=? "
                            "WHERE state_id=1 AND generation=?",
                            (
                                next_generation,
                                next_generation,
                                payload,
                                durable_generation,
                            ),
                        )
                        if updated.rowcount != 1:
                            self._loaded = False
                            raise EnvironmentCatalogStaleRevision(
                                "stale environment catalog revision; reload and retry"
                            )
                        conn.execute(
                            "DELETE FROM environment_events "
                            "WHERE generation<=?",
                            (next_generation,),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO environment_events("
                            "generation,event_digest,payload) VALUES(?,?,?)",
                            (
                                next_generation,
                                event_digest,
                                encoded_event,
                            ),
                        )
                        updated = conn.execute(
                            "UPDATE environment_state SET generation=? "
                            "WHERE state_id=1 AND generation=?",
                            (next_generation, durable_generation),
                        )
                        if updated.rowcount != 1:
                            self._loaded = False
                            raise EnvironmentCatalogStaleRevision(
                                "stale environment catalog revision; reload and retry"
                            )
            self._state_generation = next_generation
            if checkpoint_due:
                self._checkpoint_generation = next_generation
            self._clear_changes()
            self._loaded = True
        except BaseException:
            # The in-memory projection may contain a mutation that did not
            # become durable. Force authoritative reconstruction before reuse.
            self._loaded = False
            raise

    @staticmethod
    def _pairs_decode(value: list[list[str]]) -> tuple[tuple[str, str], ...]:
        return tuple((str(row[0]), str(row[1])) for row in value)

    def _rebuild_derived_indexes(self) -> None:
        self._rebuild_clean_instance_index()
        self._assignments = HierarchicalResourceResolver(
            ancestry=self._scopes.ancestry
        )
        for row in self._assignment_rows.values():
            self._assignments.bind(
                ScopedValue(
                    "execution-environment",
                    row.name,
                    row.scope,
                    row.spec_id,
                    row.policy,
                )
            )
        self._rebuild_bindings()

    def _load_snapshot_payload(self, value: dict[str, object]) -> None:
        self._profile_revisions = _TrackedDict({
            (row["profile_id"], row["profile_revision"]): EnvironmentProfileRevision(
                row["profile_id"],
                row["category_id"],
                row["profile_revision"],
                EnvironmentProfileLifecycle(row["lifecycle"]),
            )
            for row in value.get("profile_revisions", [])
        })
        self._profile_materializations = _TrackedDict({
            row["materialization_digest"]: EnvironmentProfileMaterialization(
                row["profile_id"],
                row["profile_revision"],
                row["build_input_digest"],
                row["runtime_identity_digest"],
                row["deployment_receipt_digest"],
                row["runtime_reference"],
            )
            for row in value.get("profile_materializations", [])
        })
        self._templates = _TrackedDict({
            row["template_id"]: EnvironmentTemplate(
                row["template_id"],
                ExecutionEnvironmentKind(row["kind"]),
                self._decode_scope(row["scope"]),
                row["base_spec_id"],
                row["description"],
            )
            for row in value.get("templates", [])
        })
        self._specs = _TrackedDict({
            row["spec_id"]: EnvironmentSpec(
                row["spec_id"],
                ExecutionEnvironmentKind(row["kind"]),
                self._decode_scope(row["scope"]),
                row["parent_spec_id"],
                row["template_id"],
                self._pairs_decode(row["requirements"]),
                self._pairs_decode(row["environment"]),
                tuple(row["tags"]),
            )
            for row in value.get("specs", [])
        })
        self._overlays = _TrackedDict({
            row["overlay_id"]: EnvironmentOverlay(
                row["overlay_id"],
                row["target_spec_id"],
                self._decode_scope(row["scope"]),
                self._pairs_decode(row["requirements"]),
                self._pairs_decode(row["environment"]),
            )
            for row in value.get("overlays", [])
        })
        self._instances = _TrackedDict({
            row["instance_id"]: EnvironmentInstance(
                row["instance_id"],
                row["resolved_spec_digest"],
                row["backend"],
                row["runtime_reference"],
                row["runtime_identity_digest"],
                row["materialization_digest"],
                self._decode_scope(row["scope"]),
                row["profile_id"],
                row["profile_revision"],
                EnvironmentInstanceState(row["state"]),
                int(row["generation"]),
                row["cleanliness_proof_digest"],
            )
            for row in value.get("instances", [])
        })
        self._assignment_rows = _TrackedDict({
            (
                row["name"],
                row["scope"]["kind"] + ":" + row["scope"]["scope_id"],
            ): EnvironmentAssignment(
                row["name"],
                row["spec_id"],
                self._decode_scope(row["scope"]),
                ResolutionPolicy(row["policy"]),
            )
            for row in value.get("assignments", [])
        })
        self._binding_rows = _TrackedDict({
            (
                row["role"],
                row["scope"]["kind"] + ":" + row["scope"]["scope_id"],
            ): EnvironmentBinding(
                row["binding_id"],
                self._decode_scope(row["scope"]),
                row["role"],
                row["instance_id"],
            )
            for row in value.get("bindings", [])
        })
        self._rebuild_derived_indexes()
        self._clear_changes()

    def _apply_event(self, event: dict[str, object]) -> None:
        expected_fields = {
            "schema",
            "profile_revisions",
            "profile_materializations",
            "templates",
            "specs",
            "overlays",
            "assignments",
            "instances",
            "bindings",
            "deleted_bindings",
        }
        if set(event) != expected_fields:
            raise RuntimeError("environment catalog event fields are not exact")
        if event["schema"] != "noetrium.environment-catalog-event.v1":
            raise RuntimeError("unsupported environment catalog event schema")

        for row in event["profile_revisions"]:
            value = EnvironmentProfileRevision(
                row["profile_id"],
                row["category_id"],
                row["profile_revision"],
                EnvironmentProfileLifecycle(row["lifecycle"]),
            )
            self._profile_revisions.load_set(
                (value.profile_id, value.profile_revision),
                value,
            )
        for row in event["profile_materializations"]:
            value = EnvironmentProfileMaterialization(
                row["profile_id"],
                row["profile_revision"],
                row["build_input_digest"],
                row["runtime_identity_digest"],
                row["deployment_receipt_digest"],
                row["runtime_reference"],
            )
            self._profile_materializations.load_set(
                value.materialization_digest,
                value,
            )
        for row in event["templates"]:
            value = EnvironmentTemplate(
                row["template_id"],
                ExecutionEnvironmentKind(row["kind"]),
                self._decode_scope(row["scope"]),
                row["base_spec_id"],
                row["description"],
            )
            self._templates.load_set(value.template_id, value)
        for row in event["specs"]:
            value = EnvironmentSpec(
                row["spec_id"],
                ExecutionEnvironmentKind(row["kind"]),
                self._decode_scope(row["scope"]),
                row["parent_spec_id"],
                row["template_id"],
                self._pairs_decode(row["requirements"]),
                self._pairs_decode(row["environment"]),
                tuple(row["tags"]),
            )
            self._specs.load_set(value.spec_id, value)
        for row in event["overlays"]:
            value = EnvironmentOverlay(
                row["overlay_id"],
                row["target_spec_id"],
                self._decode_scope(row["scope"]),
                self._pairs_decode(row["requirements"]),
                self._pairs_decode(row["environment"]),
            )
            self._overlays.load_set(value.overlay_id, value)
        for row in event["assignments"]:
            value = EnvironmentAssignment(
                row["name"],
                row["spec_id"],
                self._decode_scope(row["scope"]),
                ResolutionPolicy(row["policy"]),
            )
            self._assignment_rows.load_set(
                (value.name, value.scope.key),
                value,
            )
        for row in event["instances"]:
            value = EnvironmentInstance(
                row["instance_id"],
                row["resolved_spec_digest"],
                row["backend"],
                row["runtime_reference"],
                row["runtime_identity_digest"],
                row["materialization_digest"],
                self._decode_scope(row["scope"]),
                row["profile_id"],
                row["profile_revision"],
                EnvironmentInstanceState(row["state"]),
                int(row["generation"]),
                row["cleanliness_proof_digest"],
            )
            self._instances.load_set(value.instance_id, value)
        for row in event["bindings"]:
            value = EnvironmentBinding(
                row["binding_id"],
                self._decode_scope(row["scope"]),
                row["role"],
                row["instance_id"],
            )
            self._binding_rows.load_set(
                (value.role, value.scope.key),
                value,
            )
        for row in event["deleted_bindings"]:
            if (
                not isinstance(row, list)
                or len(row) != 2
                or any(type(value) is not str for value in row)
            ):
                raise RuntimeError(
                    "environment catalog deleted binding key is invalid"
                )
            self._binding_rows.load_pop((row[0], row[1]))

    def _load(self) -> None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT schema_version,generation,checkpoint_generation "
                "FROM environment_state WHERE state_id=1"
            ).fetchone()
            if row is None or int(row[0]) != self.SCHEMA_VERSION:
                raise RuntimeError(
                    "unsupported SQLiteExecutionEnvironmentCatalog schema"
                )
            durable_generation = int(row[1])
            checkpoint_generation = int(row[2])
            if (
                self._loaded
                and durable_generation == self._state_generation
            ):
                return
            if self._loaded and self._state_generation > durable_generation:
                raise RuntimeError(
                    "environment catalog durable generation moved backwards"
                )

            if (
                not self._loaded
                or self._state_generation < checkpoint_generation
            ):
                snapshot_row = conn.execute(
                    "SELECT payload FROM environment_state WHERE state_id=1"
                ).fetchone()
                if snapshot_row is None:
                    raise RuntimeError(
                        "environment catalog checkpoint is missing"
                    )
                value = json.loads(str(snapshot_row[0]))
                if not isinstance(value, dict):
                    raise RuntimeError(
                        "environment catalog checkpoint must be an object"
                    )
                self._load_snapshot_payload(value)
                start_generation = checkpoint_generation
            else:
                start_generation = self._state_generation

            rows = conn.execute(
                "SELECT generation,event_digest,payload "
                "FROM environment_events "
                "WHERE generation>? AND generation<=? "
                "ORDER BY generation",
                (start_generation, durable_generation),
            ).fetchall()

        expected_generation = start_generation + 1
        for generation, event_digest, payload in rows:
            generation = int(generation)
            if generation != expected_generation:
                raise RuntimeError(
                    "environment catalog event tail is not contiguous"
                )
            event = json.loads(str(payload))
            if not isinstance(event, dict):
                raise RuntimeError(
                    "environment catalog event payload must be an object"
                )
            if canonical_digest(event) != str(event_digest):
                raise RuntimeError(
                    "environment catalog event digest mismatch"
                )
            self._apply_event(event)
            expected_generation += 1
        if expected_generation - 1 != durable_generation:
            raise RuntimeError(
                "environment catalog event tail does not reach durable generation"
            )
        self._rebuild_derived_indexes()
        self._clear_changes()
        self._state_generation = durable_generation
        self._checkpoint_generation = checkpoint_generation
        self._loaded = True

    def register_profile_revision(
        self,
        profile: EnvironmentProfileRevision,
    ) -> None:
        self._load()
        super().register_profile_revision(profile)
        self._persist()

    def profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileRevision:
        self._load()
        return super().profile_revision(profile_id, profile_revision)

    def register_profile_materialization(
        self,
        materialization: EnvironmentProfileMaterialization,
    ) -> None:
        self._load()
        super().register_profile_materialization(materialization)
        self._persist()

    def profile_materialization(
        self,
        materialization_digest: str,
    ) -> EnvironmentProfileMaterialization:
        self._load()
        return super().profile_materialization(materialization_digest)

    def profile_materializations(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> tuple[EnvironmentProfileMaterialization, ...]:
        self._load()
        return super().profile_materializations(profile_id, profile_revision)

    def transition_profile_revision(
        self,
        profile_id: str,
        profile_revision: str,
        lifecycle: EnvironmentProfileLifecycle,
    ) -> EnvironmentProfileRevision:
        self._load()
        value = super().transition_profile_revision(
            profile_id,
            profile_revision,
            lifecycle,
        )
        self._persist()
        return value

    def register_template(self, template: EnvironmentTemplate) -> None:
        self._load()
        super().register_template(template)
        self._persist()

    def register_spec(self, spec: EnvironmentSpec) -> None:
        self._load()
        super().register_spec(spec)
        self._persist()

    def register_overlay(self, overlay: EnvironmentOverlay) -> None:
        self._load()
        super().register_overlay(overlay)
        self._persist()

    def assign(self, assignment: EnvironmentAssignment) -> None:
        self._load()
        super().assign(assignment)
        self._assignment_rows[(assignment.name, assignment.scope.key)] = assignment
        self._persist()

    def resolve(self, name: str, scope: ScopeIdentity) -> ResolvedEnvironmentSpec:
        self._load()
        return super().resolve(name, scope)

    def register_instance(self, instance: EnvironmentInstance) -> None:
        self._load()
        super().register_instance(instance)
        self._persist()

    def instances(self) -> tuple[EnvironmentInstance, ...]:
        self._load()
        return super().instances()

    def bindings(self) -> tuple[EnvironmentBinding, ...]:
        self._load()
        return super().bindings()

    def register_recovery_instance(
        self,
        instance: EnvironmentInstance,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> None:
        self._load()
        super().register_recovery_instance(
            instance,
            role=role,
            scope=scope,
        )
        self._persist()

    def bind(self, binding: EnvironmentBinding) -> None:
        self._load()
        super().bind(binding)
        self._persist()

    def acquire_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        binding_id: str,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceAcquisition:
        def acquire_once() -> EnvironmentInstanceAcquisition:
            self._load()
            value = ExecutionEnvironmentCatalog.acquire_reusable_instance(
                self,
                profile_id,
                profile_revision,
                runtime_identity_digest,
                materialization_digest,
                binding_id=binding_id,
                role=role,
                scope=scope,
            )
            self._persist()
            return value

        return retry_until_deadline(
            acquire_once,
            should_retry=lambda exc: isinstance(
                exc,
                EnvironmentCatalogStaleRevision,
            ),
            timeout_seconds=self.timeout_seconds,
        )

    def recover_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceAcquisition:
        def recover_once() -> EnvironmentInstanceAcquisition:
            self._load()
            value = ExecutionEnvironmentCatalog.recover_reusable_instance(
                self,
                profile_id,
                profile_revision,
                runtime_identity_digest,
                materialization_digest,
                role=role,
                scope=scope,
            )
            self._persist()
            return value

        return retry_until_deadline(
            recover_once,
            should_retry=lambda exc: isinstance(
                exc,
                EnvironmentCatalogStaleRevision,
            ),
            timeout_seconds=self.timeout_seconds,
        )

    def unbind(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding:
        self._load()
        value = super().unbind(role, scope)
        self._persist()
        return value

    def binding(self, role: str, scope: ScopeIdentity) -> EnvironmentBinding:
        self._load()
        return super().binding(role, scope)

    def release_instance(
        self,
        instance_id: str,
        *,
        cleanliness: EnvironmentCleanlinessProof | None = None,
    ) -> EnvironmentInstance:
        self._load()
        value = super().release_instance(
            instance_id,
            cleanliness=cleanliness,
        )
        self._persist()
        return value

    def mark_instance_dirty(self, instance_id: str) -> EnvironmentInstance:
        self._load()
        value = super().mark_instance_dirty(instance_id)
        self._persist()
        return value

    def destroy_instance(self, instance_id: str) -> EnvironmentInstance:
        self._load()
        value = super().destroy_instance(instance_id)
        self._persist()
        return value

    def reusable_instances(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
    ) -> tuple[EnvironmentInstance, ...]:
        self._load()
        return super().reusable_instances(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization_digest,
        )

    def profile_references(
        self,
        profile_id: str,
        profile_revision: str,
    ) -> EnvironmentProfileReferenceSummary:
        self._load()
        return super().profile_references(profile_id, profile_revision)

    def assess_profile_gc(
        self,
        profile_id: str,
        profile_revision: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentProfileGcAssessment:
        self._load()
        return super().assess_profile_gc(
            profile_id,
            profile_revision,
            closures=closures,
        )

    def runtime_references(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
    ) -> EnvironmentRuntimeReferenceSummary:
        self._load()
        return super().runtime_references(
            profile_id,
            profile_revision,
            runtime_identity_digest,
        )

    def assess_runtime_gc(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> EnvironmentRuntimeGcAssessment:
        self._load()
        return super().assess_runtime_gc(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            closures=closures,
        )


__all__ = [
    "EnvironmentCatalogConflict",
    "EnvironmentCatalogNotFound",
    "EnvironmentCatalogStaleRevision",
    "ExecutionEnvironmentCatalog",
    "SQLiteExecutionEnvironmentCatalog",
]
