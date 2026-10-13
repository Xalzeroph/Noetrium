from __future__ import annotations

import hashlib
import json
import subprocess
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from noetrium_platform.evidence.artifact.content.api import (
    ArchiveMaterializationError,
    ArchiveMaterializationRequest,
)
from noetrium_platform.evidence.artifact.content.composition import compose_artifact_acquisition
from noetrium_platform.evidence.artifact.content.providers import SafeTarArchiveMaterializer
from noetrium_platform.infrastructure.lifecycle.toolchain.api import (
    JavaRuntimePlatform,
    JavaRuntimeProvisioningRequest,
    JavaRuntimeReceipt,
    RuntimeToolchainError,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.composition import (
    compose_eclipse_adoptium_java_runtime,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.providers import AdoptiumMetadataResolver
from noetrium_platform.infrastructure.lifecycle.toolchain.providers.java_receipt import (
    encode_java_runtime_receipt,
    load_java_runtime_receipt,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.providers.java_verifier import JavaRuntimeVerifier
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        del size
        payload, self._payload = self._payload, b""
        return payload

    def close(self) -> None:
        pass


def _tar_payload(
    *,
    unsafe_member: str | None = None,
    unsafe_link: str | None = None,
) -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name in ("jdk-21.0.8", "jdk-21.0.8/bin"):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        java = b"verified-java-placeholder\n"
        info = tarfile.TarInfo("jdk-21.0.8/bin/java")
        info.size = len(java)
        info.mode = 0o755
        archive.addfile(info, BytesIO(java))
        if unsafe_member is not None:
            data = b"escape"
            info = tarfile.TarInfo(unsafe_member)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, BytesIO(data))
        if unsafe_link is not None:
            info = tarfile.TarInfo("jdk-21.0.8/escape-link")
            info.type = tarfile.SYMTYPE
            info.linkname = unsafe_link
            info.mode = 0o777
            archive.addfile(info)
    return output.getvalue()


def _request(tmp_path: Path) -> JavaRuntimeProvisioningRequest:
    root = tmp_path / "cache"
    return JavaRuntimeProvisioningRequest(
        feature_version=21,
        platform=JavaRuntimePlatform("linux", "x64"),
        archive_path=str((root / "temurin.tar.gz").resolve()),
        destination=str((root / "home").resolve()),
        receipt_path=str((root / "receipt.json").resolve()),
        scope=PLATFORM_SCOPE,
        producer_operation_id="test-operation",
    )


def test_temurin_runtime_is_verified_materialized_and_reused_without_metadata_network(
    tmp_path: Path,
) -> None:
    payload = _tar_payload()
    checksum = hashlib.sha256(payload).hexdigest()
    source_url = (
        "https://github.com/adoptium/temurin21-binaries/releases/download/"
        "jdk-21.0.8%2B9/OpenJDK21U-jdk_x64_linux_hotspot_21.0.8_9.tar.gz"
    )
    metadata = [
        {
            "vendor": "eclipse",
            "release_name": "jdk-21.0.8+9",
            "version": {"major": 21, "semver": "21.0.8+9"},
            "binary": {
                "architecture": "x64",
                "image_type": "jdk",
                "jvm_impl": "hotspot",
                "os": "linux",
                "package": {
                    "name": "OpenJDK21U-jdk_x64_linux_hotspot_21.0.8_9.tar.gz",
                    "link": source_url,
                    "checksum": checksum,
                    "size": len(payload),
                },
            },
        }
    ]
    metadata_calls: list[str] = []
    artifact_calls: list[str] = []
    command_calls: list[tuple[str, ...]] = []

    def metadata_opener(request, timeout):
        del timeout
        metadata_calls.append(request.full_url)
        return _Response(json.dumps(metadata).encode("utf-8"))

    def artifact_opener(request, timeout):
        del timeout
        artifact_calls.append(request.full_url)
        return _Response(payload)

    def runner(command, **kwargs):
        del kwargs
        command_calls.append(tuple(command))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr='openjdk version "21.0.8" 2025-07-15\nEclipse Temurin',
        )

    acquisition = compose_artifact_acquisition(opener=artifact_opener)
    materializer = SafeTarArchiveMaterializer()
    assembly = compose_eclipse_adoptium_java_runtime(
        acquisition=acquisition.acquirer,
        materialization=materializer,
        tree_inspection=materializer,
        metadata_opener=metadata_opener,
        command_runner=runner,
    )
    request = _request(tmp_path)

    first = assembly.provisioner.provision(request)
    second = assembly.provisioner.provision(request)

    assert first.archive_downloaded is True
    assert first.materialized is True
    assert second.archive_downloaded is False
    assert second.materialized is False
    assert first.receipt.digest() == second.receipt.digest()
    assert (
        Path(first.receipt.java_executable).read_bytes()
        == b"verified-java-placeholder\n"
    )
    assert Path(request.receipt_path).is_file()
    receipt_document = json.loads(Path(request.receipt_path).read_text("utf-8"))
    assert receipt_document["schema"] == "runtime.java-receipt.v2"
    assert len(receipt_document["payload_sha256"]) == 64
    assert len(metadata_calls) == 1
    assert artifact_calls == [source_url]
    assert len(command_calls) == 2

    Path(first.receipt.java_executable).write_bytes(b"tampered-java\n")
    with pytest.raises(RuntimeToolchainError, match="JAVA_EXECUTABLE_DRIFT"):
        assembly.provisioner.provision(request)


def test_adoptium_metadata_rejects_legacy_version_data_shape(tmp_path: Path) -> None:
    request = _request(tmp_path)
    legacy = [{
        "vendor": "eclipse",
        "release_name": "jdk-21.0.8+9",
        "version_data": {"major": 21, "semver": "21.0.8+9"},
        "binary": {"package": {}},
    }]

    resolver = AdoptiumMetadataResolver(
        opener=lambda request, timeout: _Response(json.dumps(legacy).encode("utf-8"))
    )
    with pytest.raises(RuntimeToolchainError) as raised:
        resolver.resolve(request)
    assert raised.value.code == "METADATA_SHAPE_INVALID"


def test_safe_tar_materializer_rejects_path_traversal_without_publication(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    archive_path.write_bytes(_tar_payload(unsafe_member="../escape"))
    destination = tmp_path / "home"

    with pytest.raises(ArchiveMaterializationError, match="UNSAFE_MEMBER_PATH"):
        SafeTarArchiveMaterializer().materialize(
            ArchiveMaterializationRequest(
                archive_path=str(archive_path.resolve()),
                destination=str(destination.resolve()),
                required_relative_paths=("bin/java",),
            )
        )

    assert not destination.exists()
    assert not (tmp_path / "escape").exists()


def test_safe_tar_materializer_rejects_symlink_escaping_single_archive_root(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "unsafe-link.tar.gz"
    archive_path.write_bytes(_tar_payload(unsafe_link="../outside"))
    destination = tmp_path / "home"

    with pytest.raises(ArchiveMaterializationError, match="UNSAFE_LINK_TARGET"):
        SafeTarArchiveMaterializer().materialize(
            ArchiveMaterializationRequest(
                archive_path=str(archive_path.resolve()),
                destination=str(destination.resolve()),
                required_relative_paths=("bin/java",),
            )
        )

    assert not destination.exists()


def test_java_runtime_receipt_checksum_tamper_fails_closed(tmp_path: Path) -> None:
    receipt = JavaRuntimeReceipt(
        provider_id="test-provider",
        feature_version=21,
        semantic_version="21.0.8+9",
        release_name="jdk-21.0.8+9",
        operating_system="linux",
        architecture="x64",
        metadata_url="https://api.adoptium.net/v3/assets/latest/21/hotspot",
        source_url="https://github.com/adoptium/temurin21-binaries/releases/download/x/a.tar.gz",
        archive_path=str((tmp_path / "a.tar.gz").resolve()),
        archive_sha256="a" * 64,
        archive_size=1,
        java_home=str((tmp_path / "home").resolve()),
        java_executable=str((tmp_path / "home" / "bin" / "java").resolve()),
        java_executable_sha256="b" * 64,
        materialized_tree_sha256="c" * 64,
        materialized_file_count=1,
        materialized_size=1,
        java_major=21,
        java_version_output_sha256="d" * 64,
    )
    path = tmp_path / "receipt.json"
    path.write_bytes(encode_java_runtime_receipt(receipt))
    document = json.loads(path.read_text("utf-8"))
    document["payload"]["release_name"] = "tampered-release"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RuntimeToolchainError) as raised:
        load_java_runtime_receipt(path)
    assert raised.value.code == "RECEIPT_INVALID"


def test_java_runtime_verifier_rejects_wrong_exact_major(tmp_path: Path) -> None:
    executable = tmp_path / "java"
    executable.write_bytes(b"placeholder")
    executable.chmod(0o755)

    def runner(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr='openjdk version "17.0.15" 2025-04-15',
        )

    with pytest.raises(RuntimeToolchainError) as raised:
        JavaRuntimeVerifier(runner).verify(executable, 21)
    assert raised.value.code == "JAVA_VERSION_MISMATCH"
