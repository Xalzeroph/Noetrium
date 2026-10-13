from __future__ import annotations

from pathlib import Path
import shutil
from urllib.parse import quote, unquote

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel import (
    FilesystemCarrierGeneration,
    FilesystemCarrierKind,
    filesystem_birth_time_ns,
    capture_filesystem_carrier_generation,
    fsync_directory,
    remove_empty_directory_carrier,
    rename_directory_carrier,
    atomic_replace_bytes,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.directory.api import (
    WORKSPACE_METADATA_FIELDS,
    WORKSPACE_METADATA_SCHEMA,
    WORKSPACE_PROVIDER_KIND,
    WorkspaceMetadataError,
    WorkspaceMetadataFailureCode,
    workspace_metadata_document_from_spec,
    workspace_name,
    workspace_realization_spec,
    workspace_resource_key,
    workspace_root_digest,
    workspace_terminal_key,
)
from noetrium_platform.infrastructure.resources.authority.api import (
    ResourceRealizationSpec,
    TicketState,
    is_physical_identity,
    is_realization_ticket,
    physical_field,
    physical_identity,
    resource_observation,
    ticket_field,
)


class WorkspacePhysicalProviderError(RuntimeError):
    pass

class WorkspacePhysicalProvider:
    """Thin filesystem provider for one Authority-addressed workspace carrier."""

    provider_kind = WORKSPACE_PROVIDER_KIND

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self._root_digest = workspace_root_digest(self.root)
        self._quarantine_root = self.root / ".retired-workspaces"

    def _parts(self, resource_key: str) -> tuple[str, str, str, str]:
        parts = resource_key.split(":", 5)
        if len(parts) != 6 or parts[0] != "workspace":
            raise WorkspacePhysicalProviderError("foreign workspace resource key")
        if parts[1] != self._root_digest:
            raise WorkspacePhysicalProviderError(
                "workspace resource belongs to another physical root"
            )
        decoded = []
        for raw, label in zip(parts[2:], ("scope kind", "scope id", "category", "workspace id"), strict=True):
            value = unquote(raw)
            if quote(value, safe="") != raw:
                raise WorkspacePhysicalProviderError(
                    f"workspace resource {label} is not canonically encoded"
                )
            decoded.append(workspace_name(value, label))
        return tuple(decoded)  # type: ignore[return-value]

    def path_for(self, resource_key: str) -> Path:
        scope_kind, scope_id, category, workspace_id = self._parts(resource_key)
        return self.root / scope_kind / scope_id / category / workspace_id

    def _quarantine_candidates(self, ticket: NoetriumUnit) -> tuple[Path, ...]:
        ticket_id = str(ticket_field(ticket, "ticket_id"))
        if not self._quarantine_root.exists():
            return ()
        rows = tuple(sorted(self._quarantine_root.glob(ticket_id + "-*")))
        if len(rows) > 1:
            raise WorkspacePhysicalProviderError(
                "one workspace ticket owns multiple quarantine carriers"
            )
        return rows

    @staticmethod
    def _quarantine_generation(path: Path, ticket_id: str) -> FilesystemCarrierGeneration:
        prefix = ticket_id + "-"
        if not path.name.startswith(prefix):
            raise WorkspacePhysicalProviderError("workspace quarantine name drifted")
        try:
            device_raw, inode_raw, birth_raw = path.name[len(prefix):].split("-", 2)
            expected_device = int(device_raw)
            expected_inode = int(inode_raw)
            expected_birth_time_ns = int(birth_raw)
        except (TypeError, ValueError) as exc:
            raise WorkspacePhysicalProviderError(
                "workspace quarantine generation name is malformed"
            ) from exc
        current = capture_filesystem_carrier_generation(
            path,
            expected_kind=FilesystemCarrierKind.DIRECTORY,
        )
        birth_time_ns = filesystem_birth_time_ns(path)
        if birth_time_ns is None:
            raise WorkspacePhysicalProviderError(
                "workspace quarantine filesystem lacks stable birth-time identity"
            )
        if (
            current.device != expected_device
            or current.inode != expected_inode
            or birth_time_ns != expected_birth_time_ns
        ):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine physical generation changed"
            )
        return current

    @staticmethod
    def _spec_from_metadata(path: Path) -> ResourceRealizationSpec:
        metadata = path / ".workspace.json"
        if metadata.is_symlink() or not metadata.is_file():
            raise WorkspacePhysicalProviderError(
                "workspace carrier lacks exact metadata projection"
            )
        return workspace_realization_spec(metadata.read_bytes())

    def _validate_metadata(self, path: Path, ticket: NoetriumUnit) -> None:
        spec = self._spec_from_metadata(path)
        if spec.semantic_digest != ticket_field(ticket, "spec_digest"):
            raise WorkspaceMetadataError(
                WorkspaceMetadataFailureCode.IDENTITY_MISMATCH
            )

    def _identity(
        self,
        ticket: NoetriumUnit,
        path: Path,
        *,
        carrier_state: str,
    ) -> NoetriumUnit:
        generation = capture_filesystem_carrier_generation(
            path,
            expected_kind=FilesystemCarrierKind.DIRECTORY,
        )
        return physical_identity(
            self.provider_kind,
            canonical_digest(
                {
                    "resource_key": ticket_field(ticket, "resource_key"),
                    "device": generation.device,
                    "inode": generation.inode,
                }
            ),
            {
                "resource_key": ticket_field(ticket, "resource_key"),
                "ticket_id": ticket_field(ticket, "ticket_id"),
                "generation": ticket_field(ticket, "generation"),
                "spec_digest": ticket_field(ticket, "spec_digest"),
                "path": str(path),
                "carrier_state": carrier_state,
                "carrier_generation": generation.to_data(),
            },
        )

    def _absent(self, ticket: NoetriumUnit) -> NoetriumUnit:
        return resource_observation(
            str(ticket_field(ticket, "resource_key")),
            int(ticket_field(ticket, "generation")),
            str(ticket_field(ticket, "ticket_id")),
            str(ticket_field(ticket, "spec_digest")),
            False,
            False,
            None,
        )

    def realize(
        self,
        spec: dict[str, object],
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        if not is_realization_ticket(ticket):
            raise TypeError("workspace realize requires realization ticket")
        frozen = ResourceRealizationSpec(self.provider_kind, spec)
        if frozen.semantic_digest != ticket_field(ticket, "spec_digest"):
            raise WorkspacePhysicalProviderError(
                "workspace realize spec drifted from Authority ticket"
            )
        try:
            raw = workspace_metadata_document_from_spec(spec)
        except (TypeError, ValueError, WorkspaceMetadataError) as exc:
            raise WorkspacePhysicalProviderError(str(exc)) from exc
        path = self.path_for(str(ticket_field(ticket, "resource_key")))
        quarantine = self._quarantine_candidates(ticket)
        if quarantine:
            raise WorkspacePhysicalProviderError(
                "workspace cannot realize while retired carrier is quarantined"
            )
        metadata = path / ".workspace.json"
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir():
                raise WorkspacePhysicalProviderError(
                    "workspace path is not an owned directory"
                )
            if metadata.exists():
                if metadata.is_symlink() or not metadata.is_file():
                    raise WorkspacePhysicalProviderError(
                        "workspace metadata path is not a regular file"
                    )
                if metadata.read_bytes() != raw:
                    raise WorkspacePhysicalProviderError(
                        "workspace existing metadata differs from Authority spec"
                    )
            else:
                if any(path.iterdir()):
                    raise WorkspacePhysicalProviderError(
                        "workspace has unowned residue before realization"
                    )
                atomic_replace_bytes(metadata, raw)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.mkdir()
            fsync_directory(path.parent)
            atomic_replace_bytes(metadata, raw)
        self._validate_metadata(path, ticket)
        return self._identity(ticket, path, carrier_state="live")

    def observe(self, reference: NoetriumUnit) -> NoetriumUnit:
        if is_realization_ticket(reference):
            ticket = reference
            path = self.path_for(str(ticket_field(ticket, "resource_key")))
            quarantine = self._quarantine_candidates(ticket)
            if path.exists() and quarantine:
                raise WorkspacePhysicalProviderError(
                    "workspace has both live and quarantine carriers"
                )
            if path.exists():
                if path.is_symlink() or not path.is_dir():
                    raise WorkspacePhysicalProviderError(
                        "workspace live carrier changed kind"
                    )
                self._validate_metadata(path, ticket)
                identity = self._identity(ticket, path, carrier_state="live")
                return resource_observation(
                    str(ticket_field(ticket, "resource_key")),
                    int(ticket_field(ticket, "generation")),
                    str(ticket_field(ticket, "ticket_id")),
                    str(ticket_field(ticket, "spec_digest")),
                    True,
                    ticket_field(ticket, "state") is not TicketState.RETIRING,
                    identity,
                )
            if quarantine:
                q = quarantine[0]
                if q.is_symlink() or not q.is_dir():
                    raise WorkspacePhysicalProviderError(
                        "workspace quarantine carrier changed kind"
                    )
                current = self._quarantine_generation(
                    q, str(ticket_field(ticket, "ticket_id"))
                )
                metadata = q / ".workspace.json"
                if metadata.exists():
                    self._validate_metadata(q, ticket)
                elif any(q.iterdir()):
                    raise WorkspacePhysicalProviderError(
                        "workspace quarantine lost metadata before becoming empty"
                    )
                identity = physical_identity(
                    self.provider_kind,
                    canonical_digest(
                        {
                            "resource_key": ticket_field(ticket, "resource_key"),
                            "device": current.device,
                            "inode": current.inode,
                        }
                    ),
                    {
                        "resource_key": ticket_field(ticket, "resource_key"),
                        "ticket_id": ticket_field(ticket, "ticket_id"),
                        "generation": ticket_field(ticket, "generation"),
                        "spec_digest": ticket_field(ticket, "spec_digest"),
                        "path": str(q),
                        "carrier_state": "quarantine",
                        "carrier_generation": current.to_data(),
                    },
                )
                return resource_observation(
                    str(ticket_field(ticket, "resource_key")),
                    int(ticket_field(ticket, "generation")),
                    str(ticket_field(ticket, "ticket_id")),
                    str(ticket_field(ticket, "spec_digest")),
                    True,
                    False,
                    identity,
                )
            return self._absent(ticket)
        if not is_physical_identity(reference):
            raise TypeError(
                "workspace observe requires ticket or physical identity"
            )
        if physical_field(reference, "provider_kind") != self.provider_kind:
            raise ValueError("foreign physical identity passed to workspace provider")
        attrs = dict(physical_field(reference, "attributes") or {})
        resource_key = str(attrs.get("resource_key") or "")
        ticket_id = str(attrs.get("ticket_id") or "")
        spec_digest = str(attrs.get("spec_digest") or "")
        generation = attrs.get("generation")
        path = Path(str(attrs.get("path") or ""))
        if (
            not resource_key
            or not ticket_id
            or not spec_digest
            or type(generation) is not int
            or generation < 1
        ):
            raise WorkspacePhysicalProviderError(
                "workspace physical identity lacks Authority coordinates"
            )
        if not path.exists():
            return resource_observation(
                resource_key, generation, ticket_id, spec_digest, False, False, None
            )
        current = capture_filesystem_carrier_generation(
            path, expected_kind=FilesystemCarrierKind.DIRECTORY
        )
        return resource_observation(
            resource_key,
            generation,
            ticket_id,
            spec_digest,
            True,
            str(attrs.get("carrier_state")) == "live",
            physical_identity(
                self.provider_kind,
                canonical_digest(
                    {"resource_key": resource_key, "device": current.device, "inode": current.inode}
                ),
                {**attrs, "carrier_generation": current.to_data()},
            ),
        )

    @staticmethod
    def _purge_quarantine(
        quarantine: Path,
        *,
        ticket_id: str,
    ) -> None:
        current = WorkspacePhysicalProvider._quarantine_generation(
            quarantine, ticket_id
        )
        metadata = quarantine / ".workspace.json"
        if metadata.exists() and (metadata.is_symlink() or not metadata.is_file()):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine metadata changed kind"
            )
        for child in tuple(quarantine.iterdir()):
            if child.name == ".workspace.json":
                continue
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
        fsync_directory(quarantine)
        after_contents = capture_filesystem_carrier_generation(
            quarantine, expected_kind=FilesystemCarrierKind.DIRECTORY
        )
        if not current.same_object(after_contents):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine object changed while purging contents"
            )
        if metadata.exists():
            metadata.unlink()
            fsync_directory(quarantine)
        empty = capture_filesystem_carrier_generation(
            quarantine, expected_kind=FilesystemCarrierKind.DIRECTORY
        )
        if not current.same_object(empty):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine object changed before root removal"
            )
        if any(quarantine.iterdir()):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine is not empty after purge"
            )
        remove_empty_directory_carrier(
            quarantine,
            expected_generation=empty,
        )

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        if not is_realization_ticket(ticket):
            raise TypeError("workspace retire requires realization ticket")
        path = self.path_for(str(ticket_field(ticket, "resource_key")))
        quarantines = self._quarantine_candidates(ticket)
        if path.exists() and quarantines:
            raise WorkspacePhysicalProviderError(
                "workspace has both live and quarantine carriers"
            )
        if path.exists():
            if path.is_symlink() or not path.is_dir():
                raise WorkspacePhysicalProviderError(
                    "workspace live carrier changed kind before retirement"
                )
            self._validate_metadata(path, ticket)
            generation = capture_filesystem_carrier_generation(
                path, expected_kind=FilesystemCarrierKind.DIRECTORY
            )
            birth_time_ns = filesystem_birth_time_ns(path)
            if birth_time_ns is None:
                raise WorkspacePhysicalProviderError(
                    "workspace filesystem lacks stable birth-time identity"
                )
            quarantine = (
                self._quarantine_root
                / (
                    f"{ticket_field(ticket, 'ticket_id')}-"
                    f"{generation.device}-{generation.inode}-{birth_time_ns}"
                )
            )
            moved = rename_directory_carrier(
                path,
                quarantine,
                expected_generation=generation,
            )
            if not generation.same_object(moved):
                raise WorkspacePhysicalProviderError(
                    "workspace physical object changed across quarantine rename"
                )
        elif quarantines:
            quarantine = quarantines[0]
            self._quarantine_generation(
                quarantine, str(ticket_field(ticket, "ticket_id"))
            )
        else:
            return self._absent(ticket)

        metadata = quarantine / ".workspace.json"
        if metadata.exists():
            self._validate_metadata(quarantine, ticket)
        elif any(quarantine.iterdir()):
            raise WorkspacePhysicalProviderError(
                "workspace quarantine lost metadata before purge completed"
            )
        self._purge_quarantine(
            quarantine,
            ticket_id=str(ticket_field(ticket, "ticket_id")),
        )
        return self._absent(ticket)


__all__ = [
    "WorkspacePhysicalProvider",
    "WorkspacePhysicalProviderError",
]
