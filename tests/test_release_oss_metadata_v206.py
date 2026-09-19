from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import release_distribution as distribution


_METADATA = (
    b"Metadata-Version: 2.4\n"
    b"Name: noetrium\n"
    b"Version: 0.43.1\n"
    b"License-Expression: Apache-2.0\n"
    b"License-File: LICENSE\n"
    b"License-File: NOTICE\n"
    b"License-File: THIRD_PARTY_NOTICES.md\n\n"
)


def _write_wheel(path: Path, *, metadata: bytes = _METADATA, omit: str | None = None) -> None:
    prefix = "noetrium_platform-0.43.1.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{prefix}/METADATA", metadata)
        for name in distribution._REQUIRED_LICENSE_FILES:
            if name != omit:
                archive.writestr(f"{prefix}/licenses/{name}", f"{name}\n")


def _add_tar_bytes(archive: tarfile.TarFile, name: str, raw: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    archive.addfile(info, io.BytesIO(raw))


def _write_sdist(path: Path, *, metadata: bytes = _METADATA, omit: str | None = None) -> None:
    prefix = "noetrium_platform-0.43.1"
    with tarfile.open(path, "w:gz") as archive:
        _add_tar_bytes(archive, f"{prefix}/PKG-INFO", metadata)
        for name in distribution._REQUIRED_LICENSE_FILES:
            if name != omit:
                _add_tar_bytes(archive, f"{prefix}/{name}", f"{name}\n".encode())


def test_distribution_oss_metadata_requires_pep639_and_packaged_legal_files(tmp_path: Path) -> None:
    wheel = tmp_path / "noetrium_platform-0.43.1-py3-none-any.whl"
    sdist = tmp_path / "noetrium_platform-0.43.1.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)

    receipt = distribution._verify_oss_metadata(wheel, sdist)

    assert receipt["license_expression"] == "Apache-2.0"
    assert receipt["license_files"] == ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]
    assert receipt["wheel_license_file_entries"] == list(distribution._REQUIRED_LICENSE_FILES)
    assert receipt["sdist_license_file_entries"] == list(distribution._REQUIRED_LICENSE_FILES)
    assert len(receipt["wheel_metadata_sha256"]) == 64
    assert len(receipt["sdist_metadata_sha256"]) == 64


def test_distribution_oss_metadata_rejects_missing_license_expression(tmp_path: Path) -> None:
    wheel = tmp_path / "noetrium_platform-0.43.1-py3-none-any.whl"
    sdist = tmp_path / "noetrium_platform-0.43.1.tar.gz"
    metadata = _METADATA.replace(b"License-Expression: Apache-2.0\n", b"")
    _write_wheel(wheel, metadata=metadata)
    _write_sdist(sdist)

    with pytest.raises(RuntimeError, match="License-Expression"):
        distribution._verify_oss_metadata(wheel, sdist)


def test_distribution_oss_metadata_rejects_missing_wheel_legal_file(tmp_path: Path) -> None:
    wheel = tmp_path / "noetrium_platform-0.43.1-py3-none-any.whl"
    sdist = tmp_path / "noetrium_platform-0.43.1.tar.gz"
    _write_wheel(wheel, omit="NOTICE")
    _write_sdist(sdist)

    with pytest.raises(RuntimeError, match="wheel is missing packaged legal files"):
        distribution._verify_oss_metadata(wheel, sdist)


def test_distribution_oss_metadata_rejects_missing_sdist_legal_file(tmp_path: Path) -> None:
    wheel = tmp_path / "noetrium_platform-0.43.1-py3-none-any.whl"
    sdist = tmp_path / "noetrium_platform-0.43.1.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist, omit="THIRD_PARTY_NOTICES.md")

    with pytest.raises(RuntimeError, match="sdist is missing packaged legal files"):
        distribution._verify_oss_metadata(wheel, sdist)
