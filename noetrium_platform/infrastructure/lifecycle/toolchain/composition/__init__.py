from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.evidence.artifact.content.api import (
    ArchiveMaterializationPort,
    ArtifactAcquisitionPort,
    ArtifactHttpOpener,
    MaterializedTreeInspectionPort,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.api import JavaRuntimeProvisioningPort
from noetrium_platform.infrastructure.lifecycle.toolchain.providers import (
    AdoptiumMetadataResolver,
    EclipseAdoptiumTemurinProvider,
    JavaCommandRunner,
    JavaRuntimeVerifier,
)


@dataclass(frozen=True, slots=True)
class JavaRuntimeToolchainAssembly:
    provisioner: JavaRuntimeProvisioningPort


def compose_eclipse_adoptium_java_runtime(
    *,
    acquisition: ArtifactAcquisitionPort,
    materialization: ArchiveMaterializationPort,
    tree_inspection: MaterializedTreeInspectionPort,
    metadata_opener: ArtifactHttpOpener | None = None,
    command_runner: JavaCommandRunner | None = None,
) -> JavaRuntimeToolchainAssembly:
    """Assemble Runtime toolchain logic over injected Artifact-system ports.

    The Runtime system owns Java toolchain identity and verification receipts. It
    does not construct Artifact providers or select Artifact persistence policy.
    Those bindings belong at an outer composition root.
    """

    metadata = AdoptiumMetadataResolver(opener=metadata_opener)
    verifier = (
        JavaRuntimeVerifier()
        if command_runner is None
        else JavaRuntimeVerifier(command_runner)
    )
    return JavaRuntimeToolchainAssembly(
        provisioner=EclipseAdoptiumTemurinProvider(
            acquisition,
            materialization,
            tree_inspection,
            metadata,
            verifier,
        )
    )


__all__ = ["JavaRuntimeToolchainAssembly", "compose_eclipse_adoptium_java_runtime"]
