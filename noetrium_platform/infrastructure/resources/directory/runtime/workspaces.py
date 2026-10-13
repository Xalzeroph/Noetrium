from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.api import (
    PLATFORM_SCOPE,
    ScopeKind,
    scope_id,
    scope_kind,
    scope_to_data,
    scope_unit,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel import (
    InterprocessFileLock,
    encode_checksummed_document,
)
from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
)
from noetrium_platform.infrastructure.resources.authority.api import (
    AuthoritySnapshot,
    PhysicalResourceProvider,
    ResourceAuthorityPort,
    ResourceRealizationSpec,
    TicketState,
    claim_field,
    resource_claim,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.directory.api import (
    WORKSPACE_METADATA_SCHEMA,
    WORKSPACE_PROVIDER_KIND,
    DirectoryLayoutPort,
    ManagedDirectoryKind,
    WorkspaceAllocation,
    WorkspaceGcAssessment,
    workspace_realization_spec,
    workspace_resource_key,
    workspace_root_digest,
    workspace_terminal_key,
)


class LocalWorkspaceManager:
    """Workspace controller over the single Resource Authority.

    Dynamic lifetime truth is only ResourceAuthority claim/ticket/binding/Event
    state. ``.workspace.json`` is a physical metadata projection. Retirement is
    represented by one permanent terminal claim; intermediate filesystem phases
    are observed/reconciled by ``WorkspacePhysicalProvider`` and are never a
    second durable state machine.
    """

    _ACTIVE_KIND = "workspace-active"
    _TERMINAL_KIND = "workspace-terminal"

    def __init__(
        self,
        directories: DirectoryLayoutPort,
        authority: ResourceAuthorityPort,
        provider: PhysicalResourceProvider,
    ) -> None:
        if not isinstance(authority, ResourceAuthorityPort):
            raise TypeError(
                "workspace manager requires the platform ResourceAuthorityPort"
            )
        if getattr(provider, "provider_kind", None) != WORKSPACE_PROVIDER_KIND:
            raise TypeError("workspace manager requires workspace.directory provider")
        self._directories = directories
        self._authority = authority
        self._provider = provider
        self._root_digest = workspace_root_digest(self._root)
        self._holder_key = "workspace-manager:" + self._root_digest
        self._terminal_holder_key = "workspace-terminal-manager:" + self._root_digest

    @property
    def _root(self) -> Path:
        return self._directories.root(ManagedDirectoryKind.WORKSPACES)

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        if (
            type(value) is not str
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError(f"invalid {label}")

    @staticmethod
    def _validate_optional_text(value: str | None, label: str) -> None:
        if value is not None and (
            type(value) is not str or not value.strip()
        ):
            raise ValueError(
                f"workspace {label} must be non-empty text or None"
            )

    @staticmethod
    def _payload(
        workspace_id: str,
        scope: NoetriumUnit,
        category: str,
        owner: str | None,
        note: str | None,
    ) -> dict[str, object]:
        return {
            "workspace_id": workspace_id,
            "scope": scope_to_data(scope),
            "category": category,
            "owner": owner,
            "note": note,
        }

    def _resource_key(
        self,
        scope: NoetriumUnit,
        category: str,
        workspace_id: str,
    ) -> str:
        return workspace_resource_key(
            self._root,
            scope_kind=scope_kind(scope).value,
            scope_id=scope_id(scope),
            category=category,
            workspace_id=workspace_id,
        )

    def _lock_path(self, resource_key: str) -> Path:
        return (
            self._directories.root(ManagedDirectoryKind.LOCKS)
            / "workspaces"
            / f"{canonical_digest(resource_key)}.lock"
        )

    @staticmethod
    def _metadata_document(payload: dict[str, object]) -> bytes:
        return encode_checksummed_document(WORKSPACE_METADATA_SCHEMA, payload)

    @staticmethod
    def _metadata_digest(payload: dict[str, object]) -> str:
        return canonical_digest(payload)

    def _topology(self, resource_key: str):
        node = resource_node(
            "workspace",
            kind=WORKSPACE_PROVIDER_KIND,
            authority_key=resource_key,
            realization=True,
        )
        return resource_topology(
            "workspace-topology:" + canonical_digest(resource_key),
            resources=(node,),
        )

    def _terminal_topology(self, terminal_key: str):
        node = resource_node(
            "terminal",
            kind="workspace.terminal",
            authority_key=terminal_key,
            realization=False,
        )
        return resource_topology(
            "workspace-terminal-topology:" + canonical_digest(terminal_key),
            resources=(node,),
        )

    @staticmethod
    def _claims(snapshot: AuthoritySnapshot, resource_key: str):
        return snapshot.current_claims_for(resource_key)

    @staticmethod
    def _one_claim(
        snapshot: AuthoritySnapshot,
        resource_key: str,
    ):
        claims = snapshot.current_claims_for(resource_key)
        if len(claims) > 1:
            raise RuntimeError(
                "workspace resource contains multiple current claims: "
                + resource_key
            )
        return None if not claims else claims[0]

    @staticmethod
    def _attrs(claim) -> dict[str, object]:
        value = thaw_json(claim_field(claim, "attributes") or {})
        if not isinstance(value, dict):
            raise RuntimeError("workspace Authority claim attributes drifted")
        return value

    def _active_claim_candidate(
        self,
        *,
        resource_key: str,
        payload: dict[str, object],
        metadata_digest: str,
        generation: int,
        owner_scope: NoetriumUnit,
        scope_generation: int,
        scope_lease_id: str | None,
    ):
        attrs = {
            "kind": self._ACTIVE_KIND,
            "workspace_root_digest": self._root_digest,
            "workspace_identity_digest": canonical_digest(
                {
                    "schema": "resource.workspace-identity.v1",
                    "scope": payload["scope"],
                    "category": payload["category"],
                    "workspace_id": payload["workspace_id"],
                }
            ),
            "workspace_metadata_digest": metadata_digest,
            "payload": payload,
        }
        return resource_claim(
            claim_id="workspace-active:"
            + canonical_digest(
                {
                    "resource_key": resource_key,
                    "metadata_digest": metadata_digest,
                }
            ),
            resource_key=resource_key,
            holder_key=self._holder_key,
            generation=generation,
            owner_scope=owner_scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
            owner_lease_id=None,
            attributes=attrs,
        )

    def _validate_active_claim(
        self,
        claim,
        *,
        resource_key: str,
        metadata_digest: str,
    ) -> None:
        attrs = self._attrs(claim)
        if (
            attrs.get("kind") != self._ACTIVE_KIND
            or claim_field(claim, "holder_key") != self._holder_key
            or claim_field(claim, "resource_key") != resource_key
            or attrs.get("workspace_metadata_digest") != metadata_digest
        ):
            raise RuntimeError(
                "workspace identity already exists with different metadata in Resource Authority"
            )

    def _terminal_claim(self, snapshot: AuthoritySnapshot, terminal_key: str):
        claim = self._one_claim(snapshot, terminal_key)
        if claim is None:
            return None
        attrs = self._attrs(claim)
        if (
            attrs.get("kind") != self._TERMINAL_KIND
            or claim_field(claim, "holder_key") != self._terminal_holder_key
        ):
            raise RuntimeError("workspace terminal Authority claim drifted")
        return claim

    def _allocation_from_claim(self, claim) -> WorkspaceAllocation:
        attrs = self._attrs(claim)
        if attrs.get("kind") != self._ACTIVE_KIND:
            raise RuntimeError("non-workspace claim entered workspace projection")
        payload = attrs.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("workspace claim lost allocation payload")
        scope_data = payload.get("scope")
        if not isinstance(scope_data, dict):
            raise RuntimeError("workspace claim lost scope payload")
        try:
            scope = scope_unit(
                ScopeKind(str(scope_data["kind"])),
                str(scope_data["scope_id"]),
            )
            workspace_id = str(payload["workspace_id"])
            category = str(payload["category"])
            owner = payload.get("owner")
            note = payload.get("note")
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("workspace claim payload is malformed") from exc
        if owner is not None and type(owner) is not str:
            raise RuntimeError("workspace claim owner drifted")
        if note is not None and type(note) is not str:
            raise RuntimeError("workspace claim note drifted")
        resource_key = str(claim_field(claim, "resource_key"))
        expected_key = self._resource_key(scope, category, workspace_id)
        if resource_key != expected_key:
            raise RuntimeError("workspace claim resource identity drifted")
        return WorkspaceAllocation(
            workspace_id,
            scope,
            category,
            self._provider.path_for(resource_key),
            owner,
            note,
        )

    def _sparse_snapshot(
        self,
        resource_key: str,
        terminal_key: str,
    ) -> AuthoritySnapshot:
        return self._authority.snapshot_for_resource_keys(
            frozenset((resource_key, terminal_key))
        )

    def allocate_workspace(
        self,
        workspace_id: str,
        *,
        scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        category: str = "default",
        owner: str | None = None,
        note: str | None = None,
    ) -> WorkspaceAllocation:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        self._validate_name(scope_id(scope), "scope_id")
        self._validate_optional_text(owner, "owner")
        self._validate_optional_text(note, "note")
        payload = self._payload(workspace_id, scope, category, owner, note)
        document = self._metadata_document(payload)
        metadata_digest = self._metadata_digest(payload)
        spec = workspace_realization_spec(document)
        resource_key = self._resource_key(scope, category, workspace_id)
        terminal_key = workspace_terminal_key(resource_key)
        topology = self._topology(resource_key)
        scope_generation, scope_lease_id = self._authority.scope_ownership_cut(
            scope,
            scope_lease=scope_lease,
        )

        with InterprocessFileLock(self._lock_path(resource_key)):
            snapshot = self._sparse_snapshot(resource_key, terminal_key)
            if self._terminal_claim(snapshot, terminal_key) is not None:
                raise RuntimeError(
                    "workspace identity is retired and cannot be reused: "
                    + workspace_id
                )
            active = self._one_claim(snapshot, resource_key)
            if active is not None:
                self._validate_active_claim(
                    active,
                    resource_key=resource_key,
                    metadata_digest=metadata_digest,
                )

            def claims(_snapshot: AuthoritySnapshot, generation: int):
                return (
                    self._active_claim_candidate(
                        resource_key=resource_key,
                        payload=payload,
                        metadata_digest=metadata_digest,
                        generation=generation,
                        owner_scope=scope,
                        scope_generation=scope_generation.generation,
                        scope_lease_id=scope_lease_id,
                    ),
                )

            self._authority.reconcile(
                topology,
                claim_candidates={"workspace": claims},
                realization_specs={
                    "workspace": lambda _snapshot: spec,
                },
                providers={self._provider.provider_kind: self._provider},
            )
            current = self._sparse_snapshot(resource_key, terminal_key)
            active = self._one_claim(current, resource_key)
            if active is None:
                raise RuntimeError("workspace realization lost Authority claim")
            self._validate_active_claim(
                active,
                resource_key=resource_key,
                metadata_digest=metadata_digest,
            )
            ticket = current.current_ticket_for(resource_key)
            if ticket is None or ticket_field(ticket, "state") is not TicketState.BOUND:
                raise RuntimeError("workspace realization did not reach BOUND")
            observation = self._provider.observe(ticket)
            if not bool(observation.attribute("exists")) or not bool(
                observation.attribute("ready")
            ):
                raise RuntimeError("workspace realization is not physically ready")
            return self._allocation_from_claim(active)

    def list_workspaces(
        self,
        *,
        scope: NoetriumUnit | None = None,
        category: str | None = None,
    ) -> tuple[WorkspaceAllocation, ...]:
        if scope is not None:
            self._validate_name(scope_id(scope), "scope_id")
        if category is not None:
            self._validate_name(category, "category")
        active_snapshot = self._authority.snapshot_for_holder(self._holder_key)
        terminal_snapshot = self._authority.snapshot_for_holder(
            self._terminal_holder_key
        )
        retired_resources = {
            str(self._attrs(claim).get("workspace_resource_key"))
            for claim in terminal_snapshot.claims
            if self._attrs(claim).get("kind") == self._TERMINAL_KIND
        }
        rows: list[WorkspaceAllocation] = []
        for claim in active_snapshot.claims:
            attrs = self._attrs(claim)
            if attrs.get("kind") != self._ACTIVE_KIND:
                raise RuntimeError("workspace holder contains foreign claim")
            resource_key = str(claim_field(claim, "resource_key"))
            if resource_key in retired_resources:
                continue
            allocation = self._allocation_from_claim(claim)
            if scope is not None and allocation.scope != scope:
                continue
            if category is not None and allocation.category != category:
                continue
            ticket = active_snapshot.current_ticket_for(resource_key)
            if ticket is None or ticket_field(ticket, "state") is not TicketState.BOUND:
                raise RuntimeError(
                    "authorized workspace lacks BOUND physical realization"
                )
            observed = self._provider.observe(ticket)
            if not bool(observed.attribute("exists")) or not bool(
                observed.attribute("ready")
            ):
                raise RuntimeError(
                    "authorized workspace physical realization is not ready"
                )
            rows.append(allocation)
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    scope_kind(row.scope).value,
                    scope_id(row.scope),
                    row.category,
                    row.workspace_id,
                ),
            )
        )

    def assess_workspace_gc(
        self,
        workspace_id: str,
        *,
        scope: NoetriumUnit,
        category: str = "default",
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> WorkspaceGcAssessment:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        resource_key = self._resource_key(scope, category, workspace_id)
        terminal_key = workspace_terminal_key(resource_key)
        with InterprocessFileLock(self._lock_path(resource_key)):
            snapshot = self._sparse_snapshot(resource_key, terminal_key)
            if (
                self._one_claim(snapshot, resource_key) is None
                and self._terminal_claim(snapshot, terminal_key) is None
            ):
                raise KeyError(
                    "workspace identity does not exist: " + workspace_id
                )
        return WorkspaceGcAssessment(
            workspace_id=workspace_id,
            scope=scope,
            category=category,
            closures=closures,
        )

    def _terminal_claim_candidate(
        self,
        *,
        terminal_key: str,
        resource_key: str,
        metadata_digest: str,
        gc: WorkspaceGcAssessment,
        generation: int,
        scope_generation: int,
    ):
        attrs = {
            "kind": self._TERMINAL_KIND,
            "workspace_root_digest": self._root_digest,
            "workspace_resource_key": resource_key,
            "workspace_identity_digest": gc.workspace_identity_digest,
            "workspace_metadata_digest": metadata_digest,
            "gc_proof_digest": gc.proof_digest,
        }
        return resource_claim(
            claim_id="workspace-terminal:"
            + canonical_digest(
                {
                    "terminal_key": terminal_key,
                    "workspace_resource_key": resource_key,
                    "gc_proof_digest": gc.proof_digest,
                    "metadata_digest": metadata_digest,
                }
            ),
            resource_key=terminal_key,
            holder_key=self._terminal_holder_key,
            generation=generation,
            owner_scope=PLATFORM_SCOPE,
            scope_generation=scope_generation,
            scope_lease_id=None,
            owner_lease_id=None,
            attributes=attrs,
        )

    def _validate_terminal_claim(
        self,
        claim,
        *,
        resource_key: str,
        metadata_digest: str,
        gc: WorkspaceGcAssessment,
    ) -> None:
        attrs = self._attrs(claim)
        if (
            attrs.get("kind") != self._TERMINAL_KIND
            or attrs.get("workspace_resource_key") != resource_key
            or attrs.get("workspace_identity_digest")
            != gc.workspace_identity_digest
            or attrs.get("workspace_metadata_digest") != metadata_digest
            or attrs.get("gc_proof_digest") != gc.proof_digest
        ):
            raise RuntimeError(
                "workspace terminal Authority fact changed across retry"
            )

    def remove_workspace(
        self,
        workspace_id: str,
        *,
        scope: NoetriumUnit,
        category: str = "default",
        gc: WorkspaceGcAssessment,
    ) -> bool:
        self._validate_name(workspace_id, "workspace_id")
        self._validate_name(category, "category")
        resource_key = self._resource_key(scope, category, workspace_id)
        terminal_key = workspace_terminal_key(resource_key)
        if (
            type(gc) is not WorkspaceGcAssessment
            or gc.workspace_id != workspace_id
            or gc.scope != scope
            or gc.category != category
            or gc.workspace_identity_digest
            != canonical_digest(
                {
                    "schema": "resource.workspace-identity.v1",
                    "scope": scope_to_data(scope),
                    "category": category,
                    "workspace_id": workspace_id,
                }
            )
        ):
            raise RuntimeError(
                "workspace GC assessment does not bind the exact workspace identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "workspace GC requires complete execution, evidence, and recovery "
                "closure with zero retained references"
            )

        topology = self._topology(resource_key)
        terminal_topology = self._terminal_topology(terminal_key)
        terminal_scope_generation, terminal_scope_lease_id = (
            self._authority.scope_ownership_cut(PLATFORM_SCOPE)
        )
        if terminal_scope_lease_id is not None:
            raise RuntimeError("platform scope unexpectedly carries a scope lease")
        with InterprocessFileLock(self._lock_path(resource_key)):
            snapshot = self._sparse_snapshot(resource_key, terminal_key)
            active = self._one_claim(snapshot, resource_key)
            terminal = self._terminal_claim(snapshot, terminal_key)
            if active is None and terminal is None:
                return False

            metadata_digest: str
            payload: dict[str, object] | None = None
            spec: ResourceRealizationSpec | None = None
            if active is not None:
                attrs = self._attrs(active)
                if attrs.get("kind") != self._ACTIVE_KIND:
                    raise RuntimeError("workspace active claim kind drifted")
                metadata_digest = str(
                    attrs.get("workspace_metadata_digest") or ""
                )
                payload_value = attrs.get("payload")
                if not isinstance(payload_value, dict):
                    raise RuntimeError("workspace active claim lost payload")
                payload = payload_value
                spec = workspace_realization_spec(
                    self._metadata_document(payload)
                )
            else:
                assert terminal is not None
                terminal_attrs = self._attrs(terminal)
                metadata_digest = str(
                    terminal_attrs.get("workspace_metadata_digest") or ""
                )
                # Exact physical spec remains durably frozen by the current or
                # historical Authority ticket; no second tombstone copy exists.

            if terminal is None:
                assert active is not None

                def terminal_claims(
                    _snapshot: AuthoritySnapshot,
                    generation: int,
                ):
                    return (
                        self._terminal_claim_candidate(
                            terminal_key=terminal_key,
                            resource_key=resource_key,
                            metadata_digest=metadata_digest,
                            gc=gc,
                            generation=generation,
                            scope_generation=terminal_scope_generation.generation,
                        ),
                    )

                self._authority.reconcile(
                    terminal_topology,
                    claim_candidates={"terminal": terminal_claims},
                    realization_specs={},
                    providers={},
                )
                terminal = self._terminal_claim(
                    self._sparse_snapshot(resource_key, terminal_key),
                    terminal_key,
                )
                if terminal is None:
                    raise RuntimeError(
                        "workspace retirement failed to publish terminal Authority fact"
                    )
            self._validate_terminal_claim(
                terminal,
                resource_key=resource_key,
                metadata_digest=metadata_digest,
                gc=gc,
            )

            # Retirement is retryable from Authority ticket truth even if an
            # earlier round already released the active claim before the physical
            # provider finished. Never infer physical absence from claim absence.
            self._authority.reconcile(
                topology,
                claim_candidates={},
                realization_specs={},
                providers={
                    self._provider.provider_kind: self._provider,
                },
                desired_resource_ids=frozenset(),
            )
            final = self._authority.snapshot_for_resource_keys(
                frozenset((resource_key, terminal_key))
            )
            ticket = final.current_ticket_for(resource_key)
            if ticket is not None:
                raise RuntimeError(
                    "workspace retirement did not converge to physical absence"
                )
            if self._one_claim(final, resource_key) is not None:
                raise RuntimeError(
                    "workspace retirement retained an active Authority claim"
                )
            return True


__all__ = ["LocalWorkspaceManager"]
