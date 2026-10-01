from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.release.api import ReleaseManifest
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from scripts.verify_installed_artifact import verify_installed_artifact


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_LICENSE_EXPRESSION = "Apache-2.0"
_REQUIRED_LICENSE_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")

_WORKSPACE_ONLY_PREFIXES = (
    "research/",
    "benchmarks/",
    "docs/research/",
)
_WORKSPACE_ONLY_EXACT = frozenset({
    ".github/workflows/research_workspace.yml",
    "scripts/project_design_trace_gate.py",
    "scripts/sync_benchmark_manifests.py",
    "scripts/sync_reproductions.py",
    "scripts/sync_publication_priority.py",
    "scripts/sync_research_pressure.py",
    "scripts/sync_research_program.py",
    "scripts/sync_lineage_status.py",
    "scripts/run_reproduction_fleet.py",
})
_WORKSPACE_ONLY_TEST_PREFIXES = (
    "tests/test_scientific_",
    "tests/test_research_",
    "tests/test_reproduction_",
    "tests/test_publication_",
    "tests/test_lineage_",
)


def _workspace_only_path(relative: str) -> bool:
    normalized = relative.replace("\\", "/").lstrip("./")
    return (
        any(normalized.startswith(prefix) for prefix in _WORKSPACE_ONLY_PREFIXES)
        or normalized in _WORKSPACE_ONLY_EXACT
        or any(normalized.startswith(prefix) for prefix in _WORKSPACE_ONLY_TEST_PREFIXES)
    )


def _project_platform_source(source_root: Path) -> dict[str, object]:
    """Physically remove research-workspace-only material before packaging.

    The repository may carry an internal paper-reproduction workspace for platform
    stress testing, but formal platform artifacts are built from a source projection
    in which that workspace does not exist.  This makes release independence a
    filesystem fact rather than a setuptools convention.
    """

    removed: list[str] = []
    files = tuple(sorted((path for path in source_root.rglob("*") if path.is_file()), key=lambda row: row.as_posix()))
    for path in files:
        relative = path.relative_to(source_root).as_posix()
        if not _workspace_only_path(relative):
            continue
        removed.append(relative)
        path.unlink()
    for path in sorted((row for row in source_root.rglob("*") if row.is_dir()), key=lambda row: len(row.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass
    raw = "\n".join(removed).encode("utf-8")
    return {
        "schema": "noetrium.platform-source-projection.v1",
        "workspace_material_physically_removed": True,
        "removed_file_count": len(removed),
        "removed_paths_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _verify_wheel_workspace_exclusion(wheel: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        wheel_paths = tuple(
            sorted(name for name in archive.namelist() if _workspace_only_path(name))
        )
    if wheel_paths:
        raise RuntimeError(
            "wheel contains source-workspace-only material: "
            f"{wheel_paths[:20]}"
        )
    return {
        "workspace_only_material_excluded": True,
        "wheel_workspace_path_count": 0,
    }


def _verify_workspace_exclusion(wheel: Path, sdist: Path) -> dict[str, object]:
    wheel_result = _verify_wheel_workspace_exclusion(wheel)
    with tarfile.open(sdist, "r:gz") as archive:
        relative_paths: list[str] = []
        for name in archive.getnames():
            parts = PurePosixPath(name).parts
            if len(parts) < 2:
                continue
            relative_paths.append(PurePosixPath(*parts[1:]).as_posix())
        sdist_paths = tuple(
            sorted(path for path in relative_paths if _workspace_only_path(path))
        )
    if sdist_paths:
        raise RuntimeError(
            "sdist contains source-workspace-only material: "
            f"{sdist_paths[:20]}"
        )
    return {
        **wheel_result,
        "sdist_workspace_path_count": 0,
    }


def _license_metadata(raw: bytes, *, artifact_kind: str) -> tuple[str, ...]:
    message = BytesParser(policy=default).parsebytes(raw)
    expression = message.get("License-Expression")
    if expression != _LICENSE_EXPRESSION:
        raise RuntimeError(f"{artifact_kind} metadata License-Expression is not Apache-2.0")
    files = tuple(message.get_all("License-File") or ())
    missing = tuple(name for name in _REQUIRED_LICENSE_FILES if name not in files)
    if missing:
        raise RuntimeError(f"{artifact_kind} metadata is missing License-File entries: {missing}")
    return files


def _verify_wheel_oss_metadata(wheel: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_names = [
            name
            for name in names
            if name.count("/") == 1 and name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise RuntimeError(
                "wheel must contain exactly one top-level dist-info METADATA"
            )
        metadata_name = metadata_names[0]
        metadata_raw = archive.read(metadata_name)
        wheel_license_files = _license_metadata(
            metadata_raw,
            artifact_kind="wheel",
        )
        dist_info = metadata_name.rsplit("/", 1)[0]
        expected = tuple(
            f"{dist_info}/licenses/{name}"
            for name in _REQUIRED_LICENSE_FILES
        )
        missing = tuple(name for name in expected if name not in names)
        if missing:
            raise RuntimeError(
                f"wheel is missing packaged legal files: {missing}"
            )

    return {
        "license_expression": _LICENSE_EXPRESSION,
        "license_files": list(_REQUIRED_LICENSE_FILES),
        "wheel_license_file_entries": list(wheel_license_files),
        "wheel_metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
    }


def _verify_oss_metadata(wheel: Path, sdist: Path) -> dict[str, object]:
    wheel_metadata = _verify_wheel_oss_metadata(wheel)
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        metadata_names = [
            name
            for name in names
            if name.count("/") == 1 and name.endswith("/PKG-INFO")
        ]
        if len(metadata_names) != 1:
            raise RuntimeError("sdist must contain exactly one top-level PKG-INFO")
        metadata_name = metadata_names[0]
        handle = archive.extractfile(metadata_name)
        if handle is None:
            raise RuntimeError("sdist PKG-INFO is unreadable")
        metadata_raw = handle.read()
        sdist_license_files = _license_metadata(
            metadata_raw,
            artifact_kind="sdist",
        )
        package_root = metadata_name.rsplit("/", 1)[0]
        expected = tuple(
            f"{package_root}/{name}"
            for name in _REQUIRED_LICENSE_FILES
        )
        missing = tuple(name for name in expected if name not in names)
        if missing:
            raise RuntimeError(
                f"sdist is missing packaged legal files: {missing}"
            )

    return {
        **wheel_metadata,
        "sdist_license_file_entries": list(sdist_license_files),
        "sdist_metadata_sha256": hashlib.sha256(metadata_raw).hexdigest(),
    }


_RUNTIME_ARTIFACT_SCHEMA = "noetrium.runtime-artifact.v1"
_RUNTIME_ARTIFACT_EVIDENCE = "RUNTIME_ARTIFACT_EVIDENCE.json"
_MATERIALIZATION_SCHEMA = "noetrium.filesystem-source-snapshot.v1"
_SOURCE_DATE_EPOCH = "315532800"


def _source_manifest(root: Path = ROOT) -> ReleaseManifest:
    return build_release_manifest(Path(root).resolve())


def _source_identity(root: Path = ROOT) -> str:
    return _source_manifest(root).source_tree_sha256


def _assert_source_identity(expected: ReleaseManifest) -> None:
    """Explicitly compare the mutable workspace against one manifest.

    Formal release construction intentionally does not call this after a source
    snapshot has been frozen: the snapshot, not the subsequently mutable worktree,
    is the authority for that release.
    """
    observed = _source_manifest(ROOT)
    if (
        observed.source_tree_sha256 != expected.source_tree_sha256
        or observed.digest() != expected.digest()
    ):
        raise RuntimeError(
            "source identity drifted during explicit workspace verification"
        )


def _materialize_exact_source(
    destination: Path,
) -> tuple[str, int, ReleaseManifest]:
    opening = _source_manifest(ROOT)
    destination.mkdir(parents=True, exist_ok=False)
    for row in opening.files:
        source = ROOT.joinpath(*row.path.split("/"))
        raw = source.read_bytes()
        if len(raw) != row.size or hashlib.sha256(raw).hexdigest() != row.sha256:
            raise RuntimeError(
                "source identity drifted during snapshot materialization: " + row.path
            )
        target = destination.joinpath(*row.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        target.chmod(0o644)

    # The copied bytes are now the immutable source authority for this run.
    # Do not re-read the mutable working tree: concurrent development after the
    # per-file digest checks must not invalidate an already frozen snapshot.
    snapshot = build_release_manifest(
        destination,
        platform_code_version=opening.platform_code_version,
        python_requires=opening.python_requires,
    )
    if (
        snapshot.source_tree_sha256 != opening.source_tree_sha256
        or snapshot.digest() != opening.digest()
    ):
        raise RuntimeError("materialized source snapshot does not match source authority")
    return opening.digest(), len(opening.files), opening


def _source_date_epoch() -> str:
    return _SOURCE_DATE_EPOCH


def _external_temp_parent() -> Path:
    candidate = Path(tempfile.gettempdir()).resolve()
    while candidate == ROOT or ROOT in candidate.parents:
        parent = candidate.parent
        if parent == candidate:
            raise RuntimeError(
                "could not select a temporary parent outside the source tree"
            )
        candidate = parent
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _normalize_sdist(path: Path, *, source_date_epoch: str) -> None:
    epoch = int(source_date_epoch)
    canonical = path.with_name(path.name + ".canonical")
    with tarfile.open(path, "r:gz") as source, canonical.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=epoch,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as target:
                for member in sorted(source.getmembers(), key=lambda row: row.name):
                    payload = None
                    if member.isfile():
                        handle = source.extractfile(member)
                        if handle is None:
                            raise RuntimeError(
                                f"sdist member payload is unavailable: {member.name}"
                            )
                        payload = handle.read()
                    member.mtime = epoch
                    member.uid = 0
                    member.gid = 0
                    member.uname = ""
                    member.gname = ""
                    member.pax_headers = {
                        key: value
                        for key, value in member.pax_headers.items()
                        if key not in {"atime", "ctime", "mtime"}
                    }
                    target.addfile(
                        member,
                        None if payload is None else io.BytesIO(payload),
                    )
    canonical.replace(path)


def _runtime_dependency_manifest(source_root: Path) -> str:
    pyproject = source_root / "pyproject.toml"
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = document.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("pyproject project metadata is missing")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(value, str) or not value.strip()
        for value in dependencies
    ):
        raise RuntimeError("project runtime dependencies are invalid")
    # Dependency declaration order has no runtime meaning. Canonicalize it so
    # source-only edits and harmless TOML reorderings keep one Docker layer.
    return "\n".join(sorted(value.strip() for value in dependencies)) + "\n"


def _build_artifacts(
    output: Path,
    *,
    sha: str,
    include_sdist: bool,
) -> tuple[Path, Path | None, dict[str, object], ReleaseManifest]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(
        prefix="noetrium-release-source-",
        dir=_external_temp_parent(),
    ) as td:
        source_root = Path(td) / "source"
        source_materialization_sha256, source_file_count, source_authority = (
            _materialize_exact_source(source_root)
        )
        if source_authority.source_tree_sha256 != sha:
            raise RuntimeError(
                "source identity drifted before formal distribution build"
            )
        platform_projection = _project_platform_source(source_root)
        manifest = build_release_manifest(source_root)
        build_assets = output / "container-build-assets"
        build_assets.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            source_root / "deploy" / "Dockerfile",
            build_assets / "Dockerfile",
        )
        shutil.copyfile(
            source_root / "deploy" / "container-entrypoint.sh",
            build_assets / "container-entrypoint.sh",
        )
        _write_text_lf(
            build_assets / "runtime-dependencies.txt",
            _runtime_dependency_manifest(source_root),
        )

        argv = [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--wheel",
        ]
        if include_sdist:
            argv.append("--sdist")
        argv.extend(("--outdir", str(output)))
        source_date_epoch = _source_date_epoch()
        build_env = os.environ.copy()
        build_env["SOURCE_DATE_EPOCH"] = source_date_epoch
        completed = subprocess.run(
            argv,
            cwd=source_root,
            env=build_env,
            text=True,
            capture_output=True,
            check=False,
        )
        command = {
            "argv": argv,
            "cwd_mode": "external-content-addressed-snapshot",
            "source_sha": sha,
            "source_date_epoch": source_date_epoch,
            "source_materialization_schema": _MATERIALIZATION_SCHEMA,
            "source_materialization_sha256": source_materialization_sha256,
            "source_materialization_file_count": source_file_count,
            "platform_source_projection": platform_projection,
            "returncode": completed.returncode,
            "stdout_sha256": hashlib.sha256(
                completed.stdout.encode()
            ).hexdigest(),
            "stderr_sha256": hashlib.sha256(
                completed.stderr.encode()
            ).hexdigest(),
        }

    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr[-4000:]
            or completed.stdout[-4000:]
            or "distribution build failed"
        )

    wheels = tuple(output.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(
            "distribution build must produce exactly one wheel"
        )

    sdists = tuple(output.glob("*.tar.gz"))
    if include_sdist:
        if len(sdists) != 1:
            raise RuntimeError(
                "distribution build must produce exactly one sdist"
            )
        _normalize_sdist(
            sdists[0],
            source_date_epoch=source_date_epoch,
        )
        sdist: Path | None = sdists[0]
    else:
        if sdists:
            raise RuntimeError(
                "runtime artifact build unexpectedly produced an sdist"
            )
        sdist = None

    return wheels[0], sdist, command, manifest


def _build_distributions(
    output: Path,
    *,
    sha: str,
) -> tuple[Path, Path, dict[str, object], ReleaseManifest]:
    wheel, sdist, command, manifest = _build_artifacts(
        output,
        sha=sha,
        include_sdist=True,
    )
    if sdist is None:
        raise AssertionError("release artifact graph did not produce sdist")
    return wheel, sdist, command, manifest


def _write_text_lf(path: Path, value: str) -> str:
    if "\r" in value:
        raise ValueError("release authority text must not contain carriage returns")
    raw = value.encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: object) -> str:
    return _write_text_lf(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _container_build_assets_authority(output: Path) -> dict[str, dict[str, object]]:
    build_assets_root = output / "container-build-assets"
    result: dict[str, dict[str, object]] = {}
    for key, filename in (
        ("dockerfile", "Dockerfile"),
        ("entrypoint", "container-entrypoint.sh"),
        ("runtime_dependencies", "runtime-dependencies.txt"),
    ):
        path = build_assets_root / filename
        result[key] = {
            "path": f"container-build-assets/{filename}",
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    return result


def _write_runtime_artifact_evidence(
    output: Path,
    *,
    sha: str,
    wheel: Path,
    build_command: dict[str, object],
    manifest: ReleaseManifest,
) -> tuple[dict[str, object], str]:
    evidence: dict[str, object] = {
        "schema": _RUNTIME_ARTIFACT_SCHEMA,
        "manifest_source": "content-addressed-filesystem-snapshot",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "agent-noetrium-system",
        "source_authority": "sha256-tree",
        "source_sha": sha,
        "source_tree_sha256": manifest.source_tree_sha256,
        "release_manifest_digest": manifest.digest(),
        "platform_version": manifest.platform_code_version,
        "python_requires": manifest.python_requires,
        "build_command": build_command,
        "oss_metadata": _verify_wheel_oss_metadata(wheel),
        "workspace_boundary": _verify_wheel_workspace_exclusion(wheel),
        "container_build_assets": _container_build_assets_authority(output),
        "artifacts": {
            wheel.name: {
                "sha256": _sha256(wheel),
                "size": wheel.stat().st_size,
            }
        },
    }
    evidence_path = output / _RUNTIME_ARTIFACT_EVIDENCE
    evidence_sha = _write_json(evidence_path, evidence)
    _write_text_lf(
        output / f"{_RUNTIME_ARTIFACT_EVIDENCE}.sha256",
        f"{evidence_sha}  {evidence_path.name}\n",
    )
    return evidence, evidence_sha


def build_runtime_artifact(output: Path) -> dict[str, object]:
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("runtime artifact output must be outside the source tree")
    source_authority = _source_manifest(ROOT)
    sha = source_authority.source_tree_sha256
    wheel, sdist, build_command, manifest = _build_artifacts(
        output,
        sha=sha,
        include_sdist=False,
    )
    if sdist is not None:
        raise AssertionError("runtime artifact closure unexpectedly contains sdist")
    evidence, _digest = _write_runtime_artifact_evidence(
        output,
        sha=sha,
        wheel=wheel,
        build_command=build_command,
        manifest=manifest,
    )
    return evidence


def _spdx_document(*, sha: str, version: str, artifacts: tuple[Path, ...]) -> dict:
    files = []
    relationships = [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": "SPDXRef-Package"}]
    for index, artifact in enumerate(artifacts, start=1):
        spdx_id = f"SPDXRef-Artifact-{index}"
        files.append({"fileName": artifact.name, "SPDXID": spdx_id, "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(artifact)}], "licenseConcluded": "NOASSERTION", "copyrightText": "NOASSERTION"})
        relationships.append({"spdxElementId": "SPDXRef-Package", "relationshipType": "CONTAINS", "relatedSpdxElement": spdx_id})
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"noetrium-{version}",
        "documentNamespace": f"https://spdx.org/spdxdocs/noetrium-{sha}",
        "creationInfo": {
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: noetrium-release-distribution"],
        },
        "packages": [{
            "name": "noetrium",
            "SPDXID": "SPDXRef-Package",
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": _LICENSE_EXPRESSION,
            "copyrightText": "NOASSERTION",
        }],
        "files": files,
        "relationships": relationships,
    }


def build_distribution_release(output: Path) -> dict:
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("distribution output must be outside the source tree")
    source_authority = _source_manifest(ROOT)
    sha = source_authority.source_tree_sha256
    wheel, sdist, build_command, manifest = _build_distributions(output, sha=sha)
    runtime_artifact, runtime_artifact_sha = _write_runtime_artifact_evidence(
        output,
        sha=sha,
        wheel=wheel,
        build_command=build_command,
        manifest=manifest,
    )
    oss_metadata = _verify_oss_metadata(wheel, sdist)
    workspace_boundary = _verify_workspace_exclusion(wheel, sdist)
    verification_refs: dict[str, dict[str, str]] = {}
    for kind, artifact in (("wheel", wheel), ("sdist", sdist)):
        receipt = verify_installed_artifact(artifact)
        path = output / f"{kind}-installed-verification.json"
        digest = _write_json(path, asdict(receipt))
        verification_refs[kind] = {"path": path.name, "sha256": digest}

    sbom_path = output / "SBOM.spdx.json"
    sbom_sha = _write_json(
        sbom_path,
        _spdx_document(sha=sha, version=manifest.platform_code_version, artifacts=(wheel, sdist)),
    )
    checksum_rows = []
    for artifact in (wheel, sdist, sbom_path):
        checksum_rows.append(f"{_sha256(artifact)}  {artifact.name}")
    checksums_path = output / "SHA256SUMS"
    checksums_sha = _write_text_lf(checksums_path, "\n".join(checksum_rows) + "\n")

    artifacts = {
        path.name: {"sha256": _sha256(path), "size": path.stat().st_size}
        for path in (wheel, sdist, sbom_path, checksums_path)
    }
    container_build_assets = runtime_artifact["container_build_assets"]
    if not isinstance(container_build_assets, dict):
        raise RuntimeError("runtime artifact container-build authority is invalid")
    evidence = {
        "schema": "noetrium.distribution-release.v5",
        "manifest_source": "content-addressed-filesystem-snapshot",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "agent-noetrium-system",
        "source_authority": "sha256-tree",
        "source_sha": sha,
        "source_tree_sha256": manifest.source_tree_sha256,
        "release_manifest_digest": manifest.digest(),
        "platform_version": manifest.platform_code_version,
        "python_requires": manifest.python_requires,
        "build_command": build_command,
        "oss_metadata": oss_metadata,
        "workspace_boundary": workspace_boundary,
        "installed_verification": verification_refs,
        "runtime_artifact": {
            "path": _RUNTIME_ARTIFACT_EVIDENCE,
            "sha256": runtime_artifact_sha,
        },
        "container_build_assets": container_build_assets,
        "artifacts": artifacts,
        "sbom_sha256": sbom_sha,
        "checksums_sha256": checksums_sha,
    }
    evidence_path = output / "DISTRIBUTION_RELEASE_EVIDENCE.json"
    evidence_sha = _write_json(evidence_path, evidence)
    sidecar = output / "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256"
    _write_text_lf(
        sidecar,
        f"{evidence_sha}  {evidence_path.name}\n",
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--required-closure",
        choices=("runtime", "release"),
        default="release",
    )
    args = parser.parse_args(argv)
    try:
        if args.required_closure == "runtime":
            evidence = build_runtime_artifact(args.output)
        else:
            evidence = build_distribution_release(args.output)
    except Exception as exc:
        print(f"DISTRIBUTION_RELEASE_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
