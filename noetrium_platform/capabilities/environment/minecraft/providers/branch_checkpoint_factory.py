from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import (
    MinecraftCheckpointPort,
    MinecraftRconEndpoint,
    MinecraftServerLifecyclePort,
    MinecraftServerEndpointBindingPort,
    MinecraftServerSpec,
)
from .branch_checkpoint import FilesystemMinecraftBranchCheckpointProvider
from .branch_restore_journal import MinecraftBranchCheckpointError
from .rcon import MinecraftRconConsole
from .world_copy import FilesystemMinecraftWorldCopier, MinecraftWorldCopier
from .world_cut_integrity import local_path as _local_path
from .world_cut_provider import FilesystemMinecraftWorldCutProvider
from .world_quiescence import MinecraftSaveQuiescenceProvider


class FilesystemMinecraftBranchCheckpointFactory:
    """Bind branch-local RCON save barriers to durable filesystem world cuts."""

    def __init__(
        self,
        *,
        snapshot_root: str | Path,
        materialization_root: str | Path,
        rcon_secret_provider: Callable[[], str],
        copier: MinecraftWorldCopier | None = None,
    ) -> None:
        if not callable(rcon_secret_provider):
            raise ValueError("branch checkpoint RCON secret provider must be callable")
        self._snapshot_root = _local_path(
            str(snapshot_root), field="checkpoint_snapshot_root"
        )
        self._materialization_root = _local_path(
            str(materialization_root), field="checkpoint_materialization_root"
        )
        self._secret = rcon_secret_provider
        self._copier = copier or FilesystemMinecraftWorldCopier()

    @staticmethod
    def _process_digest(server: MinecraftServerLifecyclePort) -> str:
        reconcile = getattr(server, "reconcile", None)
        if not callable(reconcile):
            raise MinecraftBranchCheckpointError(
                "branch checkpoint requires exact server reconciliation"
            )
        observation = reconcile()
        process = getattr(observation, "process", None)
        if process is None:
            raise MinecraftBranchCheckpointError(
                "branch server process identity is unavailable"
            )
        return canonical_digest(process)

    def create(
        self,
        *,
        server: MinecraftServerLifecyclePort,
        server_spec: MinecraftServerSpec,
        environment_generation: str,
        endpoint_binding: MinecraftServerEndpointBindingPort,
    ) -> MinecraftCheckpointPort:
        rcon: MinecraftRconEndpoint | None = server_spec.rcon_endpoint
        if rcon is None:
            raise MinecraftBranchCheckpointError(
                "authoritative branch checkpoint requires an RCON endpoint"
            )
        contract = getattr(server, "contract", None)
        digest = getattr(contract, "digest", None)
        if not callable(digest):
            raise MinecraftBranchCheckpointError(
                "branch checkpoint requires an exact server contract"
            )
        console = MinecraftRconConsole(rcon, secret_provider=self._secret)
        quiescence = MinecraftSaveQuiescenceProvider(
            console=console,
            source_workdir=server_spec.workdir,
            level_name=server_spec.level_name,
            server_contract_digest=digest(),
            process_identity_digest=lambda: self._process_digest(server),
        )
        world_cuts = FilesystemMinecraftWorldCutProvider(
            quiescence=quiescence,
            snapshot_root=self._snapshot_root,
            branch_root=self._materialization_root,
            copier=self._copier,
        )
        return FilesystemMinecraftBranchCheckpointProvider(
            server=server,
            server_spec=server_spec,
            world_cuts=world_cuts,
            environment_generation=environment_generation,
            endpoint_binding=endpoint_binding,
        )


__all__ = ["FilesystemMinecraftBranchCheckpointFactory"]
