from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import fsync_directory

from ..api import (
    MinecraftCheckpointPort,
    MinecraftRconEndpoint,
    MinecraftServerLifecyclePort,
    MinecraftServerEndpointBindingPort,
    MinecraftServerSpec,
    MinecraftWorldCut,
)
from .branch_restore_journal import (
    MinecraftBranchCheckpointError,
    MinecraftBranchRestoreJournal,
)
from .rcon import MinecraftRconConsole
from .world_copy import FilesystemMinecraftWorldCopier, MinecraftWorldCopier
from .world_cut_integrity import (
    local_path as _local_path,
    tree_manifest as _tree_manifest,
    validated_manifest as _validated_manifest,
)
from .world_cut_provider import FilesystemMinecraftWorldCutProvider
from .world_quiescence import MinecraftSaveQuiescenceProvider

class FilesystemMinecraftBranchCheckpointProvider(MinecraftCheckpointPort):
    """Crash-recoverable branch checkpoint restore over one world authority."""

    _SCHEMA = "minecraft-branch-checkpoint.v1"
    _RESTORE_SCHEMA = MinecraftBranchRestoreJournal.SCHEMA
    _RESTORE_PHASES = MinecraftBranchRestoreJournal.PHASES

    def __init__(
        self,
        *,
        server: MinecraftServerLifecyclePort,
        server_spec: MinecraftServerSpec,
        world_cuts: FilesystemMinecraftWorldCutProvider,
        environment_generation: str,
        endpoint_binding: MinecraftServerEndpointBindingPort,
    ) -> None:
        if not environment_generation.strip():
            raise ValueError("branch checkpoint requires environment generation")
        self._server = server
        self._server_spec = server_spec
        self._world_cuts = world_cuts
        self._environment_generation = environment_generation
        self._endpoint_binding = endpoint_binding
        workdir = self._workdir()
        self._restore_journal_path = workdir.parent / f".{workdir.name}.checkpoint-restore.json"
        self._restore_journal = MinecraftBranchRestoreJournal(
            path=self._restore_journal_path,
            environment_generation=self._environment_generation,
            server_workdir=self._server_spec.workdir,
            level_name=self._server_spec.level_name,
            contract_digest=self._contract_digest,
        )
        self._recover_pending_restore()

    def _workdir(self) -> Path:
        return _local_path(self._server_spec.workdir, field="server_workdir")

    def _contract_digest(self) -> str:
        contract = getattr(self._server, "contract", None)
        digest = getattr(contract, "digest", None)
        if not callable(digest):
            raise MinecraftBranchCheckpointError(
                "branch server does not expose an exact service contract digest"
            )
        value = digest()
        if not isinstance(value, str) or len(value) != 64:
            raise MinecraftBranchCheckpointError("branch server contract digest is invalid")
        return value.lower()

    def _restore_document(
        self, *, cut: MinecraftWorldCut, backup: Path, phase: str
    ) -> dict[str, JsonValue]:
        return self._restore_journal.build(cut=cut, backup=backup, phase=phase)

    def _publish_restore_document(
        self, document: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return self._restore_journal.publish(document)

    def _set_restore_phase(
        self, document: Mapping[str, JsonValue], phase: str
    ) -> dict[str, JsonValue]:
        return self._restore_journal.set_phase(document, phase)

    def _load_restore_document(self) -> dict[str, JsonValue] | None:
        return self._restore_journal.load()

    def _recover_pending_restore(self) -> str:
        document = self._load_restore_document()
        if document is None:
            return "none"
        workdir = self._workdir()
        backup = _local_path(str(document["backup_path"]), field="checkpoint_restore_backup")
        phase = str(document["phase"])
        if phase == "committed":
            if not workdir.is_dir():
                raise MinecraftBranchCheckpointError(
                    "committed branch checkpoint restore is missing its workdir"
                )
            if backup.exists():
                if backup.is_symlink() or not backup.is_dir():
                    raise MinecraftBranchCheckpointError(
                        "committed branch checkpoint restore backup is not a directory"
                    )
                shutil.rmtree(backup)
                fsync_directory(workdir.parent)
            self._restore_journal.clear()
            return "committed"

        try:
            self._server.stop()
        except BaseException as exc:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore recovery could not stop the server; filesystem state was not touched"
            ) from exc

        recovery_errors: list[BaseException] = []
        try:
            if backup.exists():
                if backup.is_symlink() or not backup.is_dir():
                    raise MinecraftBranchCheckpointError(
                        "branch checkpoint restore backup is not a directory"
                    )
                if workdir.exists():
                    if workdir.is_symlink() or not workdir.is_dir():
                        raise MinecraftBranchCheckpointError(
                            "partial restored workdir is not a directory"
                        )
                    shutil.rmtree(workdir)
                backup.rename(workdir)
                fsync_directory(workdir.parent)
            elif not workdir.is_dir():
                raise MinecraftBranchCheckpointError(
                    "branch checkpoint rollback has neither workdir nor backup"
                )
        except BaseException as exc:
            recovery_errors.append(exc)
        try:
            if workdir.is_dir():
                self._server.start()
                readiness = self._server.verify_ready()
                self._endpoint_binding.bind_ready(readiness)
        except BaseException as exc:
            recovery_errors.append(exc)
        if recovery_errors:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore recovery is incomplete: "
                + "; ".join(f"{type(exc).__name__}: {exc}" for exc in recovery_errors)
            ) from recovery_errors[0]
        self._restore_journal.clear()
        return "rolled_back"

    def capture(self, *, session_id: str, context: Any) -> bytes:
        self._recover_pending_restore()
        cut = self._world_cuts.capture(session_id=session_id, context=context)
        document = {
            "schema_version": self._SCHEMA,
            "environment_generation": self._environment_generation,
            "server_contract_digest": self._contract_digest(),
            "server_workdir": self._server_spec.workdir,
            "level_name": self._server_spec.level_name,
            "cut": cut,
        }
        return canonical_bytes(document)

    def _decode(self, payload: bytes) -> MinecraftWorldCut:
        try:
            document = json.loads(payload.decode("utf-8"))
            if document["schema_version"] != self._SCHEMA:
                raise ValueError("unsupported checkpoint schema")
            if document["environment_generation"] != self._environment_generation:
                raise ValueError("environment generation mismatch")
            if document["server_contract_digest"] != self._contract_digest():
                raise ValueError("server contract mismatch")
            if document["server_workdir"] != self._server_spec.workdir:
                raise ValueError("server workdir mismatch")
            if document["level_name"] != self._server_spec.level_name:
                raise ValueError("level name mismatch")
            cut = MinecraftWorldCut(**dict(document["cut"]))
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MinecraftBranchCheckpointError(
                "invalid or incompatible Minecraft branch checkpoint payload"
            ) from exc
        if cut.server_contract_digest != self._contract_digest():
            raise MinecraftBranchCheckpointError(
                "checkpoint cut was captured under a different server contract"
            )
        if cut.level_name != self._server_spec.level_name:
            raise MinecraftBranchCheckpointError("checkpoint cut level identity mismatch")
        return cut

    def restore(self, payload: bytes, *, session_id: str, context: Any) -> None:
        del session_id, context
        self._recover_pending_restore()
        cut = self._decode(payload)
        snapshot, document = self._world_cuts._read_cut(cut)
        expected = _validated_manifest(document.get("files"), source=str(snapshot))
        workdir = self._workdir()
        if not workdir.is_dir():
            raise MinecraftBranchCheckpointError(
                f"branch server workdir is missing before restore: {workdir}"
            )
        backup = workdir.parent / f".{workdir.name}.checkpoint-backup-{uuid4().hex}"
        restore_document = self._publish_restore_document(
            self._restore_document(cut=cut, backup=backup, phase="prepared")
        )
        primary: BaseException | None = None
        try:
            self._server.stop()
            workdir.rename(backup)
            fsync_directory(workdir.parent)
            restore_document = self._set_restore_phase(restore_document, "backup_published")
            self._world_cuts.copier.copy(snapshot, workdir)
            if _tree_manifest(workdir) != expected:
                raise MinecraftBranchCheckpointError(
                    "restored branch workdir does not match checkpoint manifest"
                )
            self._server.start()
            readiness = self._server.verify_ready()
            self._endpoint_binding.bind_ready(readiness)
            restore_document = self._set_restore_phase(restore_document, "committed")
            shutil.rmtree(backup)
            fsync_directory(workdir.parent)
            self._restore_journal.clear()
            return
        except BaseException as exc:
            primary = exc

        try:
            disposition = self._recover_pending_restore()
        except BaseException as recovery_exc:
            raise MinecraftBranchCheckpointError(
                "Minecraft checkpoint restore failed and crash recovery was incomplete: "
                f"primary={type(primary).__name__}: {primary}; "
                f"recovery={type(recovery_exc).__name__}: {recovery_exc}"
            ) from primary
        if disposition == "committed":
            return
        raise MinecraftBranchCheckpointError(
            f"Minecraft checkpoint restore failed and previous workdir was restored: {primary}"
        ) from primary

__all__ = [
    "FilesystemMinecraftBranchCheckpointProvider",
    "MinecraftBranchCheckpointError",
]
