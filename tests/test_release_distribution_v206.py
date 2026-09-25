from __future__ import annotations

import hashlib
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import scripts.release_distribution as distribution
import scripts.verify_installed_artifact as installed_artifact
from scripts.verify_installed_artifact import verify_installed_artifact


def test_formal_distribution_requires_clean_exact_git_source(monkeypatch):
    def dirty_git(*args: str) -> str:
        if args[:2] == ("status", "--porcelain=v1"):
            return " M noetrium_platform/api.py"
        raise AssertionError(args)

    monkeypatch.setattr(distribution, "_git", dirty_git)
    with pytest.raises(RuntimeError, match="clean source tree"):
        distribution._require_clean_source()


def test_clean_source_identity_returns_exact_sha_and_branch(monkeypatch):
    values = {
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
        ("rev-parse", "HEAD"): "a" * 40,
        ("branch", "--show-current"): "system/06-product-assurance-convergence",
    }
    monkeypatch.setattr(distribution, "_git", lambda *args: values[args])
    assert distribution._require_clean_source() == ("a" * 40, "system/06-product-assurance-convergence")


def test_spdx_binds_distribution_artifact_sha256():
    local_root = distribution.ROOT / ".local"
    local_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="spdx-test-", dir=local_root) as td:
        artifact = Path(td) / "noetrium_platform.whl"
        artifact.write_bytes(b"wheel-bytes")
        document = distribution._spdx_document(
            sha="b" * 40,
            version="9.9.9",
            artifacts=(artifact,),
        )
        assert document["documentNamespace"].endswith("b" * 40)
        checksum = document["files"][0]["checksums"][0]["checksumValue"]
        assert checksum == hashlib.sha256(b"wheel-bytes").hexdigest()
        assert document["packages"][0]["licenseDeclared"] == "Apache-2.0"


def test_distribution_output_must_be_outside_source_tree():
    with pytest.raises(ValueError, match="outside the source tree"):
        distribution.build_distribution_release(distribution.ROOT / "dist-role06")


def test_installed_artifact_verifier_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        verify_installed_artifact(distribution.ROOT / ".local" / "missing-role06.whl")



def test_installed_artifact_verifier_fails_closed_when_venv_is_unavailable(tmp_path: Path, monkeypatch):
    artifact = tmp_path / "noetrium_platform.whl"
    artifact.write_bytes(b"wheel")

    def unavailable(root: Path) -> None:
        del root
        raise RuntimeError("Python venv module is unavailable")

    monkeypatch.setattr(installed_artifact, "_create_venv", unavailable)
    with pytest.raises(RuntimeError, match="venv module is unavailable"):
        verify_installed_artifact(artifact)


def test_release_authority_text_writer_uses_portable_lf_bytes():
    local_root = distribution.ROOT / ".local"
    local_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="release-lf-", dir=local_root) as td:
        path = Path(td) / "SHA256SUMS"
        digest = distribution._write_text_lf(path, "abc  artifact.whl\ndef  artifact.tar.gz\n")
        raw = path.read_bytes()
        assert raw == b"abc  artifact.whl\ndef  artifact.tar.gz\n"
        assert b"\r" not in raw
        assert digest == hashlib.sha256(raw).hexdigest()


def test_release_authority_text_writer_rejects_carriage_returns():
    local_root = distribution.ROOT / ".local"
    local_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="release-cr-", dir=local_root) as td:
        path = Path(td) / "SHA256SUMS"
        with pytest.raises(ValueError, match="carriage returns"):
            distribution._write_text_lf(path, "abc  artifact.whl\r\n")
        assert not path.exists()


def test_distribution_build_runs_from_external_exact_source(monkeypatch):
    local_root = distribution.ROOT / ".local"
    local_root.mkdir(parents=True, exist_ok=True)
    seen: dict[str, Path] = {}

    def fake_materialize(sha: str, destination: Path) -> str:
        assert sha == "a" * 40
        destination.mkdir(parents=True, exist_ok=False)
        seen["source"] = destination.resolve()
        return "b" * 64, 123

    def fake_run(argv, *, cwd, text, capture_output, check):
        source_root = Path(cwd).resolve()
        assert source_root == seen["source"]
        assert source_root != distribution.ROOT
        assert distribution.ROOT not in source_root.parents
        output = Path(argv[-1])
        (output / "noetrium_platform-1.0-py3-none-any.whl").write_bytes(b"wheel")
        (output / "noetrium_platform-1.0.tar.gz").write_bytes(b"sdist")
        return type("Completed", (), {
            "returncode": 0,
            "stdout": "build-ok",
            "stderr": "",
        })()

    def fake_manifest(root: Path):
        resolved = Path(root).resolve()
        assert resolved == seen["source"]
        seen["manifest_root"] = resolved
        return distribution.ReleaseManifest(1, (), "c" * 64, ">=3.11", "1.0")

    monkeypatch.setattr(distribution, "_materialize_exact_source", fake_materialize)
    monkeypatch.setattr(distribution, "build_release_manifest", fake_manifest)
    monkeypatch.setattr(distribution.subprocess, "run", fake_run)
    with TemporaryDirectory(prefix="release-build-test-", dir=local_root) as td:
        output = Path(td) / "dist"
        wheel, sdist, receipt, manifest = distribution._build_distributions(
            output,
            sha="a" * 40,
        )
    assert wheel.name.endswith(".whl")
    assert sdist.name.endswith(".tar.gz")
    assert receipt["cwd_mode"] == "external-git-object-database"
    assert receipt["source_sha"] == "a" * 40
    assert receipt["source_materialization_schema"] == distribution._MATERIALIZATION_SCHEMA
    assert receipt["source_materialization_sha256"] == "b" * 64
    assert receipt["source_materialization_file_count"] == 123
    assert manifest.platform_code_version
    assert manifest.source_tree_sha256 == "c" * 64
    assert seen["manifest_root"] == seen["source"]


def test_exact_source_materialization_uses_raw_git_objects_not_export_attributes(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitattributes").write_text(
        "ignored.py export-ignore\nsubstituted.txt export-subst\n", encoding="utf-8"
    )
    ignored = b"TRACKED_BUT_EXPORT_IGNORED = True\n"
    substituted = b"$Format:%H$\n"
    (repo / "ignored.py").write_bytes(ignored)
    (repo / "substituted.txt").write_bytes(substituted)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=role06-test", "-c", "user.email=role06@test.invalid", "commit", "-qm", "fixture"],
        cwd=repo,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()
    archive_path = tmp_path / "archive.tar"
    subprocess.run(["git", "archive", "-o", str(archive_path), sha], cwd=repo, check=True)
    with tarfile.open(archive_path, "r:") as archive:
        names = set(archive.getnames())
        assert "ignored.py" not in names
        member = archive.extractfile("substituted.txt")
        assert member is not None and member.read() != substituted
    monkeypatch.setattr(distribution, "ROOT", repo)
    destination = tmp_path / "materialized"
    digest, file_count = distribution._materialize_exact_source(sha, destination)
    assert file_count == 3
    assert len(digest) == 64
    assert (destination / "ignored.py").read_bytes() == ignored
    assert (destination / "substituted.txt").read_bytes() == substituted

def test_distribution_closing_source_identity_rejects_clean_head_drift(monkeypatch):
    expected_sha = "a" * 40
    expected_branch = "system/06-product-assurance-convergence"
    values = {
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
        ("rev-parse", "HEAD"): "b" * 40,
        ("branch", "--show-current"): expected_branch,
    }
    monkeypatch.setattr(distribution, "_git", lambda *args: values[args])
    with pytest.raises(RuntimeError, match="source identity drifted"):
        distribution._assert_source_identity(expected_sha, expected_branch)


def test_distribution_closing_source_identity_rejects_dirty_tree(monkeypatch):
    expected_sha = "a" * 40
    expected_branch = "system/06-product-assurance-convergence"
    values = {
        ("status", "--porcelain=v1", "--untracked-files=all"): " M noetrium_platform/api.py",
        ("rev-parse", "HEAD"): expected_sha,
        ("branch", "--show-current"): expected_branch,
    }
    monkeypatch.setattr(distribution, "_git", lambda *args: values[args])
    with pytest.raises(RuntimeError, match="source identity drifted"):
        distribution._assert_source_identity(expected_sha, expected_branch)
