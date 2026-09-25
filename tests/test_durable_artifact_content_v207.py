from __future__ import annotations

import io
import os
import stat
from pathlib import Path
import tarfile
import threading

from noetrium_platform.evidence.artifact.content.api import (
    ArchiveMaterializationError,
    ArchiveMaterializationRequest,
)
from noetrium_platform.evidence.artifact.content.providers import SafeTarArchiveMaterializer
from noetrium_platform.evidence.artifact.content.providers._tar_plan import plan_tar_archive


def _archive(path: Path, payload: bytes = b"verified-java\n") -> None:
    with tarfile.open(path, "w:gz") as archive:
        directory = tarfile.TarInfo("runtime")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        bin_dir = tarfile.TarInfo("runtime/bin")
        bin_dir.type = tarfile.DIRTYPE
        bin_dir.mode = 0o755
        archive.addfile(bin_dir)
        java = tarfile.TarInfo("runtime/bin/java")
        java.size = len(payload)
        java.mode = 0o755
        archive.addfile(java, io.BytesIO(payload))


def _request(archive: Path, destination: Path) -> ArchiveMaterializationRequest:
    return ArchiveMaterializationRequest(
        archive_path=str(archive.resolve()),
        destination=str(destination.resolve()),
        required_relative_paths=("bin/java",),
    )


def test_materialized_tree_is_reverified_after_atomic_publication(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    destination = tmp_path / "runtime-home"
    _archive(archive)
    materializer = SafeTarArchiveMaterializer()

    result = materializer.materialize(_request(archive, destination))
    inspection = materializer.inspect(str(destination))

    assert result.tree_sha256 == inspection.tree_sha256
    assert result.file_count == inspection.file_count == 1
    assert result.expanded_size == inspection.expanded_size == len(b"verified-java\n")
    assert (destination / "bin" / "java").read_bytes() == b"verified-java\n"


def test_concurrent_publication_has_one_winner_and_no_overwrite(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    destination = tmp_path / "runtime-home"
    _archive(archive)
    barrier = threading.Barrier(2)
    successes = []
    failures: list[ArchiveMaterializationError] = []

    def publish() -> None:
        barrier.wait()
        try:
            successes.append(SafeTarArchiveMaterializer().materialize(_request(archive, destination)))
        except ArchiveMaterializationError as exc:
            failures.append(exc)

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code in {"DESTINATION_EXISTS", "PUBLICATION_BUSY"}
    final = SafeTarArchiveMaterializer().inspect(str(destination))
    assert final.tree_sha256 == successes[0].tree_sha256
    assert (destination / "bin" / "java").read_bytes() == b"verified-java\n"


def test_tree_digest_changes_when_published_content_changes(tmp_path: Path) -> None:
    archive = tmp_path / "runtime.tar.gz"
    destination = tmp_path / "runtime-home"
    _archive(archive)
    materializer = SafeTarArchiveMaterializer()
    result = materializer.materialize(_request(archive, destination))

    (destination / "bin" / "java").write_bytes(b"tampered\n")
    inspection = materializer.inspect(str(destination))

    assert inspection.tree_sha256 != result.tree_sha256


def test_member_nested_below_symlink_is_rejected_before_extraction(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink-parent.tar.gz"
    destination = tmp_path / "runtime-home"
    with tarfile.open(archive_path, "w:gz") as archive:
        root = tarfile.TarInfo("runtime")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        link = tarfile.TarInfo("runtime/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "bin"
        archive.addfile(link)
        nested = tarfile.TarInfo("runtime/link/java")
        nested.size = 1
        archive.addfile(nested, io.BytesIO(b"x"))

    request = ArchiveMaterializationRequest(
        archive_path=str(archive_path.resolve()),
        destination=str(destination.resolve()),
    )
    try:
        SafeTarArchiveMaterializer().materialize(request)
    except ArchiveMaterializationError as exc:
        assert exc.code == "SYMLINK_PARENT"
    else:
        raise AssertionError("symlink-parent archive must fail closed")
    assert not destination.exists()


def test_restrictive_tar_modes_remain_owner_materializable(tmp_path: Path) -> None:
    archive_path = tmp_path / "restrictive.tar.gz"
    destination = tmp_path / "runtime-home"
    payload = b"owner-readable\n"
    with tarfile.open(archive_path, "w:gz") as archive:
        root = tarfile.TarInfo("runtime")
        root.type = tarfile.DIRTYPE
        root.mode = 0
        archive.addfile(root)
        file = tarfile.TarInfo("runtime/data.txt")
        file.mode = 0
        file.size = len(payload)
        archive.addfile(file, io.BytesIO(payload))

    result = SafeTarArchiveMaterializer().materialize(
        ArchiveMaterializationRequest(
            archive_path=str(archive_path.resolve()),
            destination=str(destination.resolve()),
            required_relative_paths=("data.txt",),
        )
    )
    assert result.file_count == 1
    assert (destination / "data.txt").read_bytes() == payload
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o700
        assert stat.S_IMODE((destination / "data.txt").stat().st_mode) == 0o400


def test_forward_hardlink_chain_resolves_to_regular_source(tmp_path: Path) -> None:
    archive_path = tmp_path / "hardlink-chain.tar.gz"
    destination = tmp_path / "runtime-home"
    payload = b"verified-hardlink\n"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("runtime", "runtime/bin"):
            directory = tarfile.TarInfo(name)
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
        alias2 = tarfile.TarInfo("runtime/bin/alias2")
        alias2.type = tarfile.LNKTYPE
        alias2.linkname = "runtime/bin/alias1"
        archive.addfile(alias2)
        alias1 = tarfile.TarInfo("runtime/bin/alias1")
        alias1.type = tarfile.LNKTYPE
        alias1.linkname = "runtime/bin/base"
        archive.addfile(alias1)
        base = tarfile.TarInfo("runtime/bin/base")
        base.size = len(payload)
        archive.addfile(base, io.BytesIO(payload))

    request = ArchiveMaterializationRequest(
        archive_path=str(archive_path.resolve()),
        destination=str(destination.resolve()),
        required_relative_paths=("bin/alias2",),
    )
    result = SafeTarArchiveMaterializer().materialize(request)
    assert result.file_count == 3
    assert (destination / "bin" / "base").read_bytes() == payload
    assert (destination / "bin" / "alias1").read_bytes() == payload
    assert (destination / "bin" / "alias2").read_bytes() == payload
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) & 0o700 == 0o700
        assert stat.S_IMODE((destination / "bin").stat().st_mode) & 0o700 == 0o700
        assert stat.S_IMODE((destination / "bin" / "base").stat().st_mode) & 0o400 == 0o400



def test_hardlink_logical_size_counts_against_expansion_budget(tmp_path: Path) -> None:
    archive_path = tmp_path / "hardlink-budget.tar.gz"
    destination = tmp_path / "runtime-home"
    payload = b"12345678"
    with tarfile.open(archive_path, "w:gz") as archive:
        root = tarfile.TarInfo("runtime")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        base = tarfile.TarInfo("runtime/base")
        base.size = len(payload)
        archive.addfile(base, io.BytesIO(payload))
        for name in ("alias1", "alias2"):
            alias = tarfile.TarInfo(f"runtime/{name}")
            alias.type = tarfile.LNKTYPE
            alias.linkname = "runtime/base"
            archive.addfile(alias)

    request = ArchiveMaterializationRequest(
        archive_path=str(archive_path.resolve()),
        destination=str(destination.resolve()),
        max_expanded_size=len(payload) * 2,
    )
    try:
        SafeTarArchiveMaterializer().materialize(request)
    except ArchiveMaterializationError as exc:
        assert exc.code == "EXPANDED_SIZE_LIMIT"
    else:
        raise AssertionError("hardlink logical expansion must be budgeted")
    assert not destination.exists()


def test_long_hardlink_chain_does_not_depend_on_python_recursion(tmp_path: Path) -> None:
    archive_path = tmp_path / "long-hardlink-chain.tar.gz"
    chain_length = 1100
    with tarfile.open(archive_path, "w:gz") as archive:
        root = tarfile.TarInfo("runtime")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for index in range(chain_length - 1, -1, -1):
            alias = tarfile.TarInfo(f"runtime/a{index}")
            alias.type = tarfile.LNKTYPE
            alias.linkname = (
                "runtime/base" if index == chain_length - 1 else f"runtime/a{index + 1}"
            )
            archive.addfile(alias)
        base = tarfile.TarInfo("runtime/base")
        base.size = 0
        archive.addfile(base, io.BytesIO(b""))

    with tarfile.open(archive_path, "r:*") as archive:
        plan = plan_tar_archive(
            archive,
            max_members=chain_length + 2,
            max_expanded_size=1,
        )
    first = next(member for member in plan.members if member.key == "runtime/a0")
    assert first.hardlink_source is not None
    assert first.hardlink_source.as_posix() == "runtime/base"
