from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

import scripts.prepare_container_context as context
import scripts.verify_container_image as container

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
WHEEL_SHA = "b" * 64
DIST_SHA = "c" * 64


def _receipt(argv: list[str]) -> container.CommandReceipt:
    empty = hashlib.sha256(b"").hexdigest()
    return container.CommandReceipt(
        argv=tuple(argv), returncode=0, stdout_sha256=empty,
        stderr_sha256=empty, stdout_tail="", stderr_tail="",
    )


def _inspect(*, revision: str = SHA, wheel: str = WHEEL_SHA,
             distribution: str = DIST_SHA, user: str = "platform") -> list[dict]:
    return [{
        "Id": "sha256:" + "d" * 64,
        "RepoDigests": ["noetrium@test-digest"],
        "Config": {
            "Labels": {
                "org.opencontainers.image.revision": revision,
                container._WHEEL_LABEL: wheel,
                container._DISTRIBUTION_LABEL: distribution,
            },
            "User": user,
        },
    }]


def _smoke(*, uid: int = 10001, gid: int = 10001,
           wheel: str = WHEEL_SHA, verified: int = 2557) -> dict:
    return {
        "actions": list(container._ACTIONS),
        "module_file": "/usr/local/lib/python3.12/site-packages/noetrium_platform/api.py",
        "package_version": "0.43.1",
        "python_version": "3.12.10",
        "wheel_sha256": wheel,
        "record_verified_files": verified,
        "effective_uid": uid,
        "effective_gid": gid,
    }


def _fake_outputs(inspect_document: list[dict], smoke: dict):
    outputs = iter((
        json.dumps(inspect_document),
        "Python 3.12.10\nplatform_state_dir=/var/lib/noetrium writable=true\n",
        container._MARKER + json.dumps(smoke) + "\n",
    ))
    return lambda argv: (_receipt(argv), next(outputs))

def test_container_definition_uses_only_prebuilt_distribution_wheel():
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY *.whl" in dockerfile
    assert "COPY noetrium_platform " not in dockerfile
    assert "python -m pip wheel" not in dockerfile
    assert "PLATFORM_WHEEL_SHA256" in dockerfile
    assert "PLATFORM_DISTRIBUTION_EVIDENCE_SHA256" in dockerfile
    assert container._WHEEL_LABEL in dockerfile
    assert container._DISTRIBUTION_LABEL in dockerfile
    assert "sha256sum -c -" in dockerfile
    assert 'mkdir -p "$(dirname "$PLATFORM_EMBEDDED_WHEEL")"' in dockerfile
    assert "USER platform" in dockerfile


def test_container_smoke_verifies_wheel_record_and_effective_identity():
    script = container._product_smoke_script(WHEEL_SHA)
    assert "PLATFORM_EMBEDDED_WHEEL" in script
    assert "zipfile.ZipFile" in script
    assert ".dist-info/RECORD" in script
    assert 'distribution("noetrium")' in script
    assert 'version("noetrium")' in script
    assert "hashlib.sha256(target.read_bytes()).digest()" in script
    assert "os.geteuid()" in script
    assert "os.getegid()" in script
    assert "installed RECORD digest mismatch" in script
    assert script.index("installed RECORD digest mismatch") < script.index("noetrium --help")
    continuation = [line for line in script.splitlines() if "build_reference_application" in line]
    assert len(continuation) == 1
    assert continuation[0].endswith("\\")
    assert not continuation[0].endswith("\\\\")
    for action in container._ACTIONS:
        assert action in script


def test_container_verifier_rejects_source_revision_drift(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(revision="e" * 40), _smoke()))
    with pytest.raises(RuntimeError, match="source revision"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )

def test_container_verifier_rejects_forged_wheel_label(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(wheel="f" * 64), _smoke()))
    with pytest.raises(RuntimeError, match="wheel digest label"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )


def test_container_verifier_rejects_distribution_receipt_drift(monkeypatch):
    monkeypatch.setattr(
        container, "_run", _fake_outputs(_inspect(distribution="f" * 64), _smoke())
    )
    with pytest.raises(RuntimeError, match="distribution evidence label"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )


def test_container_verifier_rejects_declared_root_runtime_user(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(user="root"), _smoke()))
    with pytest.raises(RuntimeError, match="declare root"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )

def test_container_verifier_rejects_effective_root_even_when_config_user_is_platform(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(), _smoke(uid=0, gid=0)))
    with pytest.raises(RuntimeError, match="effective uid/gid"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )


def test_container_verifier_rejects_unverified_installed_record(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(), _smoke(verified=0)))
    with pytest.raises(RuntimeError, match="RECORD"):
        container.verify_container_image(
            "noetrium:test", expected_source_sha=SHA,
            expected_wheel_sha256=WHEEL_SHA,
            expected_distribution_evidence_sha256=DIST_SHA,
        )


def test_container_verifier_returns_distribution_bound_receipt(monkeypatch):
    monkeypatch.setattr(container, "_run", _fake_outputs(_inspect(), _smoke()))
    result = container.verify_container_image(
        "noetrium:test", expected_source_sha=SHA,
        expected_wheel_sha256=WHEEL_SHA,
        expected_distribution_evidence_sha256=DIST_SHA,
    )
    assert result.schema == "noetrium.container-verification.v3"
    assert result.qualification_scope == "operator-smoke-only"
    assert result.npe_verified is False
    assert result.operator_smoke_actions == ("run", "inspect", "stop", "resume", "reconcile", "evidence")
    assert result.source_sha == SHA
    assert result.wheel_sha256 == WHEEL_SHA
    assert result.distribution_evidence_sha256 == DIST_SHA
    assert result.effective_uid == result.effective_gid == 10001
    assert result.record_verified_files == 2557
    assert all("--network=none" in receipt.argv for receipt in result.commands[1:])

def _write_distribution_evidence(
    dist: Path, wheel: Path, *, wheel_sha: str, tree_sha: str
) -> Path:
    evidence = {
        "schema": context._DISTRIBUTION_SCHEMA,
        "source_sha": SHA,
        "source_tree_sha256": tree_sha,
        "manifest_source": "external-git-object-database",
        "release_manifest_digest": "f" * 64,
        "build_command": {
            "source_sha": SHA,
            "cwd_mode": "external-git-object-database",
            "source_materialization_schema": "noetrium.git-object-materialization.v1",
            "source_materialization_sha256": "9" * 64,
            "source_materialization_file_count": 3000,
        },
        "oss_metadata": {"license_expression": "Apache-2.0", "license_files": ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]},
        "artifacts": {wheel.name: {"sha256": wheel_sha, "size": wheel.stat().st_size}},
    }
    evidence_path = dist / "DISTRIBUTION_RELEASE_EVIDENCE.json"
    raw = (json.dumps(evidence, sort_keys=True) + "\n").encode("utf-8")
    evidence_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (dist / "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256").write_bytes(
        f"{digest}  {evidence_path.name}\n".encode("utf-8")
    )
    return evidence_path


def test_prepare_context_rejects_distribution_wheel_byte_drift(monkeypatch):
    local = ROOT / ".local"
    local.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="container-context-", dir=local) as td:
        root = Path(td)
        dist = root / "dist"
        dist.mkdir()
        wheel = dist / "noetrium_platform-1.0-py3-none-any.whl"
        wheel.write_bytes(b"actual-wheel")
        _write_distribution_evidence(
            dist, wheel, wheel_sha=hashlib.sha256(b"other-wheel").hexdigest(), tree_sha="d" * 64
        )
        monkeypatch.setattr(context, "_git_blob", lambda sha, path: b"exact")
        with pytest.raises(ValueError, match="wheel bytes"):
            context.prepare_container_context(dist, root / "ctx", expected_source_sha=SHA)


def test_prepare_context_uses_exact_git_blobs_not_mutable_checkout(monkeypatch):
    local = ROOT / ".local"
    local.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="container-context-", dir=local) as td:
        root = Path(td)
        dist = root / "dist"
        dist.mkdir()
        wheel = dist / "noetrium_platform-1.0-py3-none-any.whl"
        wheel.write_bytes(b"exact-wheel")
        wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
        evidence_path = _write_distribution_evidence(
            dist, wheel, wheel_sha=wheel_sha, tree_sha="e" * 64
        )
        blobs = {
            "deploy/Dockerfile": b"FROM exact\n",
            "deploy/container-entrypoint.sh": b"#!/bin/sh\n",
        }
        seen: list[tuple[str, str]] = []
        def fake_blob(sha: str, path: str) -> bytes:
            seen.append((sha, path))
            return blobs[path]
        monkeypatch.setattr(context, "_git_blob", fake_blob)
        output = root / "ctx"
        receipt = context.prepare_container_context(dist, output, expected_source_sha=SHA)
        assert seen == [(SHA, "deploy/Dockerfile"), (SHA, "deploy/container-entrypoint.sh")]
        assert (output / wheel.name).read_bytes() == b"exact-wheel"
        assert (output / "Dockerfile").read_bytes() == b"FROM exact\n"
        assert receipt.wheel_sha256 == wheel_sha
        assert receipt.distribution_evidence_sha256 == hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def test_ci_builds_container_from_formal_distribution_context():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/prepare_container_context.py" in workflow
    assert '"$RUNNER_TEMP/research-container-context"' in workflow
    assert 'docker build \\' in workflow
    assert '--build-arg PLATFORM_WHEEL_SHA256="${ROLE06_WHEEL_SHA256}"' in workflow
    assert '--expected-wheel-sha256 "${ROLE06_WHEEL_SHA256}"' in workflow
    assert '--expected-distribution-evidence-sha256' in workflow
    assert "--file deploy/Dockerfile ." not in workflow


def test_prepare_context_rejects_tampered_distribution_evidence_sidecar(monkeypatch):
    local = ROOT / ".local"
    local.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="container-context-sidecar-", dir=local) as td:
        root = Path(td)
        dist = root / "dist"
        dist.mkdir()
        wheel = dist / "noetrium_platform-1.0-py3-none-any.whl"
        wheel.write_bytes(b"exact-wheel")
        _write_distribution_evidence(
            dist,
            wheel,
            wheel_sha=hashlib.sha256(wheel.read_bytes()).hexdigest(),
            tree_sha="e" * 64,
        )
        (dist / "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256").write_text(
            "0" * 64 + "  DISTRIBUTION_RELEASE_EVIDENCE.json\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(context, "_git_blob", lambda sha, path: b"exact")
        with pytest.raises(ValueError, match="sidecar mismatch"):
            context.prepare_container_context(dist, root / "ctx", expected_source_sha=SHA)


def test_prepare_context_rejects_missing_oss_metadata_authority(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "noetrium_platform-1.0-py3-none-any.whl"
    wheel.write_bytes(b"exact-wheel")
    evidence_path = _write_distribution_evidence(
        dist,
        wheel,
        wheel_sha=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        tree_sha="d" * 64,
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence.pop("oss_metadata")
    raw = (json.dumps(evidence, sort_keys=True) + "\n").encode("utf-8")
    evidence_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (dist / "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256").write_bytes(
        f"{digest}  {evidence_path.name}\n".encode("utf-8")
    )

    with pytest.raises(ValueError, match="OSS metadata authority is missing"):
        context.prepare_container_context(dist, tmp_path / "ctx", expected_source_sha=SHA)
