from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import scripts.release_distribution as distribution
import scripts.verify_installed_artifact as installed_artifact
from scripts.verify_installed_artifact import verify_installed_artifact


def _minimal_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname="noetrium"\nversion="1.0"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )


def test_source_identity_is_content_addressed(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _minimal_project(source)
    (source / "payload.txt").write_text("alpha\n", encoding="utf-8")
    monkeypatch.setattr(distribution, "ROOT", source)
    first = distribution._source_manifest(source)
    assert distribution._source_identity(source) == first.source_tree_sha256
    (source / "payload.txt").write_text("beta\n", encoding="utf-8")
    second = distribution._source_manifest(source)
    assert second.source_tree_sha256 != first.source_tree_sha256


def test_source_identity_fails_closed_on_content_drift(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _minimal_project(source)
    payload = source / "payload.txt"
    payload.write_text("alpha\n", encoding="utf-8")
    monkeypatch.setattr(distribution, "ROOT", source)
    authority = distribution._source_manifest(source)
    payload.write_text("beta\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="source identity drifted"):
        distribution._assert_source_identity(authority)


def test_source_date_epoch_is_vcs_independent_and_deterministic():
    assert distribution._source_date_epoch() == "315532800"


def test_spdx_binds_distribution_artifact_sha256(tmp_path: Path):
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel-bytes")
    document = distribution._spdx_document(
        sha="b" * 64, version="9.9.9", artifacts=(artifact,)
    )
    assert document["documentNamespace"].endswith("b" * 64)
    checksum = document["files"][0]["checksums"][0]["checksumValue"]
    assert checksum == hashlib.sha256(b"wheel-bytes").hexdigest()
    assert document["packages"][0]["licenseDeclared"] == "Apache-2.0"


def test_sdist_normalization_removes_archive_time_variance(tmp_path: Path):
    def create(path: Path, *, mtime: int) -> None:
        import gzip

        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="source.tar", mode="wb", fileobj=raw, mtime=mtime
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    info = tarfile.TarInfo("pkg/example.txt")
                    payload = b"same-content\n"
                    info.size = len(payload)
                    info.mtime = mtime
                    info.uid = 123
                    info.gid = 456
                    info.uname = "builder"
                    info.gname = "builder"
                    archive.addfile(info, io.BytesIO(payload))

    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    create(first, mtime=1700000010)
    create(second, mtime=1700000999)
    distribution._normalize_sdist(first, source_date_epoch="1700000000")
    distribution._normalize_sdist(second, source_date_epoch="1700000000")
    assert first.read_bytes() == second.read_bytes()


def test_distribution_output_must_be_outside_source_tree():
    with pytest.raises(ValueError, match="outside the source tree"):
        distribution.build_distribution_release(distribution.ROOT / "dist-role06")


def test_installed_artifact_verifier_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        verify_installed_artifact(tmp_path / "missing-role06.whl")


def test_installed_artifact_verifier_reuses_qualified_dependency_environment() -> None:
    source = (
        installed_artifact.Path(installed_artifact.__file__).read_text(
            encoding="utf-8"
        )
    )
    assert "system_site_packages=True" in source
    assert '"--no-deps"' in source
    assert '"--no-build-isolation"' in source


def test_installed_artifact_verifier_fails_closed_when_venv_is_unavailable(
    tmp_path: Path, monkeypatch
):
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")

    def unavailable(root: Path) -> None:
        del root
        raise RuntimeError("Python venv module is unavailable")

    monkeypatch.setattr(installed_artifact, "_create_venv", unavailable)
    with pytest.raises(RuntimeError, match="venv module is unavailable"):
        verify_installed_artifact(artifact)


def test_release_authority_text_writer_uses_portable_lf_bytes(tmp_path: Path):
    path = tmp_path / "SHA256SUMS"
    digest = distribution._write_text_lf(
        path, "abc  artifact.whl\ndef  artifact.tar.gz\n"
    )
    raw = path.read_bytes()
    assert raw == b"abc  artifact.whl\ndef  artifact.tar.gz\n"
    assert b"\r" not in raw
    assert digest == hashlib.sha256(raw).hexdigest()


def test_release_authority_text_writer_rejects_carriage_returns(tmp_path: Path):
    path = tmp_path / "SHA256SUMS"
    with pytest.raises(ValueError, match="carriage returns"):
        distribution._write_text_lf(path, "abc  artifact.whl\r\n")
    assert not path.exists()


def test_distribution_build_runs_from_external_content_snapshot(
    monkeypatch, tmp_path: Path
):
    seen: dict[str, Path] = {}
    authority = distribution.ReleaseManifest(1, (), "a" * 64, ">=3.11", "1.0")

    def fake_materialize(destination: Path):
        destination.mkdir(parents=True, exist_ok=False)
        seen["source"] = destination.resolve()
        (destination / "deploy").mkdir()
        (destination / "deploy" / "Dockerfile").write_text(
            "FROM exact\n", encoding="utf-8"
        )
        (destination / "deploy" / "container-entrypoint.sh").write_text(
            "#!/bin/sh\n", encoding="utf-8"
        )
        (destination / "pyproject.toml").write_text(
            "[project]\n"
            "name='noetrium'\n"
            "version='1.0'\n"
            "dependencies=['httpx>=0.28,<0.29']\n",
            encoding="utf-8",
        )
        return "b" * 64, 123, authority

    def fake_run(argv, *, cwd, env, text, capture_output, check):
        source_root = Path(cwd).resolve()
        assert source_root == seen["source"]
        assert source_root != distribution.ROOT
        assert distribution.ROOT not in source_root.parents
        assert env["SOURCE_DATE_EPOCH"] == "315532800"
        output = Path(argv[-1])
        (output / "noetrium_platform-1.0-py3-none-any.whl").write_bytes(b"wheel")
        sdist_path = output / "noetrium_platform-1.0.tar.gz"
        with tarfile.open(sdist_path, "w:gz") as archive:
            info = tarfile.TarInfo("noetrium_platform-1.0/PKG-INFO")
            payload = (
                b"Metadata-Version: 2.1\n"
                b"Name: noetrium-platform\n"
                b"Version: 1.0\n"
            )
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        return type(
            "Completed", (), {"returncode": 0, "stdout": "build-ok", "stderr": ""}
        )()
    def fake_manifest(root: Path):
        resolved = Path(root).resolve()
        assert resolved == seen["source"]
        seen["manifest_root"] = resolved
        return distribution.ReleaseManifest(1, (), "c" * 64, ">=3.11", "1.0")

    monkeypatch.setattr(
        distribution, "_materialize_exact_source", fake_materialize
    )
    monkeypatch.setattr(distribution, "build_release_manifest", fake_manifest)
    monkeypatch.setattr(distribution.subprocess, "run", fake_run)

    with TemporaryDirectory(prefix="release-build-test-", dir=tmp_path) as td:
        output = Path(td) / "dist"
        wheel, sdist, receipt, manifest = distribution._build_distributions(
            output, sha="a" * 64
        )

    assert wheel.name.endswith(".whl")
    assert sdist.name.endswith(".tar.gz")
    assert receipt["cwd_mode"] == "external-content-addressed-snapshot"
    assert receipt["source_sha"] == "a" * 64
    assert receipt["source_date_epoch"] == "315532800"
    assert (
        receipt["source_materialization_schema"]
        == distribution._MATERIALIZATION_SCHEMA
    )
    assert receipt["source_materialization_sha256"] == "b" * 64
    assert receipt["source_materialization_file_count"] == 123
    assert manifest.source_tree_sha256 == "c" * 64
    assert seen["manifest_root"] == seen["source"]


def test_exact_source_materialization_uses_filesystem_bytes(
    monkeypatch, tmp_path: Path
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _minimal_project(repo)
    ignored = b"NOT_VCS_FILTERED = True\n"
    payload = b"$Format:%H$\n"
    (repo / "ignored.py").write_bytes(ignored)
    (repo / "substituted.txt").write_bytes(payload)
    monkeypatch.setattr(distribution, "ROOT", repo)

    destination = tmp_path / "materialized"
    digest, file_count, authority = distribution._materialize_exact_source(
        destination
    )
    assert file_count == 3
    assert len(digest) == 64
    assert authority.source_tree_sha256 == distribution._source_identity(repo)
    assert (destination / "ignored.py").read_bytes() == ignored
    assert (destination / "substituted.txt").read_bytes() == payload


def test_source_snapshot_ignores_local_runtime_material(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _minimal_project(source)
    (source / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=alpha\n", encoding="utf-8")
    (source / "run.log").write_text("first\n", encoding="utf-8")
    (source / "state.sqlite").write_bytes(b"state-a")
    (source / ".runtime-assets").mkdir()
    (source / ".runtime-assets" / "cache.bin").write_bytes(b"cache-a")
    monkeypatch.setattr(distribution, "ROOT", source)
    first = distribution._source_manifest(source)
    paths = {row.path for row in first.files}
    assert ".env" not in paths
    assert "run.log" not in paths
    assert "state.sqlite" not in paths
    assert not any(path.startswith(".runtime-assets/") for path in paths)
    (source / ".env").write_text("SECRET=beta\n", encoding="utf-8")
    (source / "run.log").write_text("second\n", encoding="utf-8")
    (source / "state.sqlite").write_bytes(b"state-b")
    second = distribution._source_manifest(source)
    assert second.source_tree_sha256 == first.source_tree_sha256


def test_source_snapshot_ignores_pytest_worker_roots(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    _minimal_project(source)
    (source / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    worker = source / "pytest-of-ubuntu"
    worker.mkdir()
    (worker / "ephemeral.txt").write_text("one\n", encoding="utf-8")
    monkeypatch.setattr(distribution, "ROOT", source)
    first = distribution._source_manifest(source)
    (worker / "ephemeral.txt").write_text("two\n", encoding="utf-8")
    second = distribution._source_manifest(source)
    assert first.source_tree_sha256 == second.source_tree_sha256
    assert not any(row.path.startswith("pytest-of-") for row in first.files)


def test_release_path_contains_no_git_subprocess_contract():
    text = Path(distribution.__file__).read_text(encoding="utf-8")
    assert '["git"' not in text
    assert '("git"' not in text
    assert "git-object-materialization" not in text
    assert "external-git-object-database" not in text
