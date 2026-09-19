from __future__ import annotations

import noetrium_platform.capabilities.environment.minecraft.providers as providers
import noetrium_platform.capabilities.environment.minecraft.providers.world_copy as world_copy
import noetrium_platform.capabilities.environment.minecraft.providers.world_cut as world_cut
import noetrium_platform.capabilities.environment.minecraft.providers.world_cut_integrity as integrity


def test_world_cut_facade_preserves_public_copier_and_error_identities() -> None:
    assert world_cut.MinecraftWorldCutError is integrity.MinecraftWorldCutError
    assert world_cut.MinecraftWorldCopier is world_copy.MinecraftWorldCopier
    assert (
        world_cut.FilesystemMinecraftWorldCopier
        is world_copy.FilesystemMinecraftWorldCopier
    )
    assert world_cut.ReflinkMinecraftWorldCopier is world_copy.ReflinkMinecraftWorldCopier
    assert providers.FilesystemMinecraftWorldCopier is world_copy.FilesystemMinecraftWorldCopier
    assert providers.ReflinkMinecraftWorldCopier is world_copy.ReflinkMinecraftWorldCopier


def test_world_cut_facade_keeps_manifest_diagnostic_aliases() -> None:
    assert world_cut._tree_manifest is integrity.tree_manifest
    assert world_cut._excluded is integrity.excluded
    assert world_cut._sha256 is integrity.sha256_file


def test_world_cut_facade_reexports_provider_module_identity() -> None:
    import noetrium_platform.capabilities.environment.minecraft.providers.world_cut_provider as provider

    assert (
        world_cut.FilesystemMinecraftWorldCutProvider
        is provider.FilesystemMinecraftWorldCutProvider
    )
    assert (
        world_cut.FilesystemMinecraftWorldCutMetadataStore
        is provider.FilesystemMinecraftWorldCutMetadataStore
    )


def test_world_cut_facade_reexports_checkpoint_module_identity() -> None:
    import noetrium_platform.capabilities.environment.minecraft.providers.branch_checkpoint as checkpoint
    import noetrium_platform.capabilities.environment.minecraft.providers.branch_checkpoint_factory as factory

    assert (
        world_cut.FilesystemMinecraftBranchCheckpointProvider
        is checkpoint.FilesystemMinecraftBranchCheckpointProvider
    )
    assert (
        world_cut.FilesystemMinecraftBranchCheckpointFactory
        is factory.FilesystemMinecraftBranchCheckpointFactory
    )
    assert world_cut.MinecraftBranchCheckpointError is checkpoint.MinecraftBranchCheckpointError
