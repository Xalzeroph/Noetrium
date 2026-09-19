from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.evidence.artifact.catalog.api import ArtifactKind, ArtifactRetention
from noetrium_platform.evidence.artifact.content.api import (
    ArchiveMaterializationPort,
    ArchiveMaterializationRequest,
    ArtifactAcquisitionPort,
    ArtifactAcquisitionRequest,
    MaterializedTreeInspectionPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock
from noetrium_platform.infrastructure.lifecycle.toolchain.api import (
    JavaRuntimeProvisioningPort,
    JavaRuntimeProvisioningRequest,
    JavaRuntimeProvisioningResult,
    JavaRuntimeReceipt,
    RuntimeToolchainError,
)

from .adoptium_metadata import (
    TemurinMetadataResolverPort,
    metadata_url,
    validate_official_download_url,
)
from .java_receipt import encode_java_runtime_receipt, load_java_runtime_receipt
from .java_verifier import JavaRuntimeVerifierPort, sha256_file

_PROVIDER_ID = "eclipse-adoptium.temurin.v4"


class EclipseAdoptiumTemurinProvider(JavaRuntimeProvisioningPort):
    """Temurin provisioning orchestrator over explicit metadata/artifact/verifier ports."""

    def __init__(
        self,
        acquisition: ArtifactAcquisitionPort,
        materialization: ArchiveMaterializationPort,
        tree_inspection: MaterializedTreeInspectionPort,
        metadata: TemurinMetadataResolverPort,
        verifier: JavaRuntimeVerifierPort,
    ) -> None:
        self._acquisition = acquisition
        self._materialization = materialization
        self._tree_inspection = tree_inspection
        self._metadata = metadata
        self._verifier = verifier

    def _reuse(
        self,
        request: JavaRuntimeProvisioningRequest,
        destination: Path,
        archive_path: Path,
        receipt_path: Path,
    ) -> JavaRuntimeProvisioningResult:
        if receipt_path.is_symlink():
            raise RuntimeToolchainError(
                "RECEIPT_INVALID",
                f"Java runtime receipt must not be a symlink: {receipt_path}",
            )
        receipt = load_java_runtime_receipt(receipt_path)
        validate_official_download_url(receipt.source_url, request.feature_version)
        expected_java = destination / "bin" / "java"
        expected = (
            _PROVIDER_ID,
            request.feature_version,
            request.platform.operating_system,
            request.platform.architecture,
            metadata_url(request),
            str(archive_path),
            str(destination),
            str(expected_java),
        )
        actual = (
            receipt.provider_id,
            receipt.feature_version,
            receipt.operating_system,
            receipt.architecture,
            receipt.metadata_url,
            receipt.archive_path,
            receipt.java_home,
            receipt.java_executable,
        )
        if actual != expected:
            raise RuntimeToolchainError(
                "RECEIPT_IDENTITY_MISMATCH",
                "cached Java runtime receipt does not match the requested platform or paths",
            )
        if not archive_path.is_file() or archive_path.is_symlink():
            raise RuntimeToolchainError(
                "ARCHIVE_MISSING", f"cached Java archive is missing: {archive_path}"
            )
        archive_sha256, archive_size = sha256_file(archive_path)
        if (archive_sha256, archive_size) != (
            receipt.archive_sha256,
            receipt.archive_size,
        ):
            raise RuntimeToolchainError(
                "ARCHIVE_DRIFT", "cached Java archive digest or size changed"
            )
        verification = self._verifier.verify(expected_java, request.feature_version)
        if verification.executable_sha256 != receipt.java_executable_sha256:
            raise RuntimeToolchainError(
                "JAVA_EXECUTABLE_DRIFT", "cached Java executable changed"
            )
        if (
            verification.major != receipt.java_major
            or hashlib.sha256(verification.version_output.encode("utf-8")).hexdigest()
            != receipt.java_version_output_sha256
        ):
            raise RuntimeToolchainError(
                "JAVA_VERSION_DRIFT", "cached Java version output changed"
            )
        tree = self._tree_inspection.inspect(str(destination))
        if (
            tree.tree_sha256,
            tree.file_count,
            tree.expanded_size,
        ) != (
            receipt.materialized_tree_sha256,
            receipt.materialized_file_count,
            receipt.materialized_size,
        ):
            raise RuntimeToolchainError(
                "RUNTIME_TREE_DRIFT", "cached Java runtime tree changed"
            )
        return JavaRuntimeProvisioningResult(receipt, False, False)

    def provision(
        self,
        request: JavaRuntimeProvisioningRequest,
    ) -> JavaRuntimeProvisioningResult:
        destination = Path(request.destination).resolve()
        archive_path = Path(request.archive_path).resolve()
        receipt_path = Path(request.receipt_path).resolve()
        if len({destination, archive_path, receipt_path}) != 3:
            raise RuntimeToolchainError(
                "CACHE_LAYOUT_INVALID",
                "Java runtime archive, destination, and receipt paths must be distinct",
            )
        if destination in archive_path.parents or destination in receipt_path.parents:
            raise RuntimeToolchainError(
                "CACHE_LAYOUT_INVALID",
                "Java runtime archive and receipt must be outside the materialized tree",
            )
        lock_path = receipt_path.with_name(receipt_path.name + ".lock")
        with InterprocessFileLock(lock_path):
            return self._provision_locked(
                request, destination, archive_path, receipt_path
            )

    def _provision_locked(
        self,
        request: JavaRuntimeProvisioningRequest,
        destination: Path,
        archive_path: Path,
        receipt_path: Path,
    ) -> JavaRuntimeProvisioningResult:
        present = tuple(
            path.exists() or path.is_symlink()
            for path in (destination, archive_path, receipt_path)
        )
        if any(present):
            if not all(present):
                raise RuntimeToolchainError(
                    "CACHE_STATE_INCOMPLETE",
                    "Java runtime cache must contain the archive, materialized tree, and receipt together",
                )
            return self._reuse(request, destination, archive_path, receipt_path)

        info = self._metadata.resolve(request)
        acquisition = self._acquisition.acquire(
            ArtifactAcquisitionRequest(
                artifact_id=(
                    f"java.temurin.{info.semantic_version}."
                    f"{request.platform.operating_system}.{request.platform.architecture}"
                ),
                source_url=info.source_url,
                destination=str(archive_path),
                scope=request.scope,
                kind=ArtifactKind.RUNTIME,
                producer_component_id="runtime.toolchain.java.temurin",
                producer_operation_id=request.producer_operation_id,
                media_type="application/gzip",
                retention=ArtifactRetention.PROJECT,
                expected_sha256=info.sha256,
                expected_size=info.size,
                timeout_s=request.timeout_s,
            )
        )
        self._materialization.materialize(
            ArchiveMaterializationRequest(
                archive_path=str(archive_path),
                destination=str(destination),
                required_relative_paths=("bin/java",),
            )
        )
        java_executable = destination / "bin" / "java"
        verification = self._verifier.verify(
            java_executable, request.feature_version
        )
        # Verification can cause distribution-specific one-time initialization;
        # inspect the final tree only after that external effect converges.
        materialized = self._tree_inspection.inspect(str(destination))
        receipt = JavaRuntimeReceipt(
            provider_id=_PROVIDER_ID,
            feature_version=request.feature_version,
            semantic_version=info.semantic_version,
            release_name=info.release_name,
            operating_system=request.platform.operating_system,
            architecture=request.platform.architecture,
            metadata_url=info.metadata_url,
            source_url=info.source_url,
            archive_path=str(archive_path),
            archive_sha256=acquisition.sha256,
            archive_size=acquisition.size,
            java_home=str(destination),
            java_executable=str(java_executable),
            java_executable_sha256=verification.executable_sha256,
            materialized_tree_sha256=materialized.tree_sha256,
            materialized_file_count=materialized.file_count,
            materialized_size=materialized.expanded_size,
            java_major=verification.major,
            java_version_output_sha256=hashlib.sha256(
                verification.version_output.encode("utf-8")
            ).hexdigest(),
        )
        atomic_replace_bytes(receipt_path, encode_java_runtime_receipt(receipt))
        return JavaRuntimeProvisioningResult(
            receipt, acquisition.downloaded, True
        )


__all__ = ["EclipseAdoptiumTemurinProvider"]
