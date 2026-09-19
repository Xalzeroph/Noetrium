from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import tarfile
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


def _verify_oss_metadata(wheel: Path, sdist: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_names = [name for name in names if name.count("/") == 1 and name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise RuntimeError("wheel must contain exactly one top-level dist-info METADATA")
        metadata_name = metadata_names[0]
        metadata_raw = archive.read(metadata_name)
        wheel_metadata_raw = metadata_raw
        wheel_license_files = _license_metadata(metadata_raw, artifact_kind="wheel")
        dist_info = metadata_name.rsplit("/", 1)[0]
        expected = tuple(f"{dist_info}/licenses/{name}" for name in _REQUIRED_LICENSE_FILES)
        missing = tuple(name for name in expected if name not in names)
        if missing:
            raise RuntimeError(f"wheel is missing packaged legal files: {missing}")

    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        metadata_names = [name for name in names if name.count("/") == 1 and name.endswith("/PKG-INFO")]
        if len(metadata_names) != 1:
            raise RuntimeError("sdist must contain exactly one top-level PKG-INFO")
        metadata_name = metadata_names[0]
        handle = archive.extractfile(metadata_name)
        if handle is None:
            raise RuntimeError("sdist PKG-INFO is unreadable")
        metadata_raw = handle.read()
        sdist_metadata_raw = metadata_raw
        sdist_license_files = _license_metadata(metadata_raw, artifact_kind="sdist")
        package_root = metadata_name.rsplit("/", 1)[0]
        expected = tuple(f"{package_root}/{name}" for name in _REQUIRED_LICENSE_FILES)
        missing = tuple(name for name in expected if name not in names)
        if missing:
            raise RuntimeError(f"sdist is missing packaged legal files: {missing}")

    return {
        "license_expression": _LICENSE_EXPRESSION,
        "license_files": list(_REQUIRED_LICENSE_FILES),
        "wheel_license_file_entries": list(wheel_license_files),
        "sdist_license_file_entries": list(sdist_license_files),
        "wheel_metadata_sha256": hashlib.sha256(wheel_metadata_raw).hexdigest(),
        "sdist_metadata_sha256": hashlib.sha256(sdist_metadata_raw).hexdigest(),
    }


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _require_clean_source() -> tuple[str, str]:
    dirty = _git("status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise RuntimeError("formal distribution release requires a clean source tree")
    return _git("rev-parse", "HEAD"), _git("branch", "--show-current")


def _assert_source_identity(expected_sha: str, expected_branch: str) -> None:
    dirty = _git("status", "--porcelain=v1", "--untracked-files=all")
    observed_sha = _git("rev-parse", "HEAD")
    observed_branch = _git("branch", "--show-current")
    if dirty or observed_sha != expected_sha or observed_branch != expected_branch:
        raise RuntimeError("source identity drifted during formal distribution qualification")


@dataclass(frozen=True, slots=True)
class GitBlobEntry:
    mode: str
    oid: str
    path: str


_MATERIALIZATION_SCHEMA = "noetrium.git-object-materialization.v1"
_REGULAR_MODES = frozenset({"100644", "100755"})


def _external_temp_parent() -> Path:
    """Select a temporary parent that cannot be inside the source checkout.

    CI and remote workstations may redirect the process temp directory into the
    checkout. Formal release qualification must still build from an independent
    materialized source tree, so walk upward until the candidate is outside ROOT.
    """

    candidate = Path(tempfile.gettempdir()).resolve()
    while candidate == ROOT or ROOT in candidate.parents:
        parent = candidate.parent
        if parent == candidate:
            raise RuntimeError("could not select a temporary parent outside the source tree")
        candidate = parent
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _git_tree_entries(sha: str) -> tuple[GitBlobEntry, ...]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", sha],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace").strip() or "git ls-tree failed")
    entries: list[GitBlobEntry] = []
    portable_paths: set[str] = set()
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        if not separator:
            raise RuntimeError("git ls-tree emitted malformed entry")
        try:
            mode, object_type, oid = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError("git tree contains non-canonical source identity") from exc
        parts = PurePosixPath(relative).parts
        if not relative or relative.startswith("/") or "\\" in relative or any(part in {"", ".", ".."} for part in parts):
            raise RuntimeError(f"unsafe tracked source path: {relative!r}")
        portable = relative.casefold()
        if portable in portable_paths:
            raise RuntimeError(f"tracked source path is not portable across case-insensitive hosts: {relative!r}")
        portable_paths.add(portable)
        if object_type != "blob":
            raise RuntimeError(f"tracked non-blob source entry is unsupported: {relative!r} ({object_type})")
        if mode not in _REGULAR_MODES:
            raise RuntimeError(f"tracked source mode is not host-neutral: {relative!r} ({mode})")
        entries.append(GitBlobEntry(mode=mode, oid=oid, path=relative))
    if not entries:
        raise RuntimeError("exact Git source tree is empty")
    return tuple(entries)


def _git_blob_batch(entries: tuple[GitBlobEntry, ...]) -> tuple[bytes, ...]:
    query = b"".join(entry.oid.encode("ascii") + b"\n" for entry in entries)
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=query,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace").strip() or "git cat-file --batch failed")
    raw = completed.stdout
    cursor = 0
    blobs: list[bytes] = []
    for entry in entries:
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            raise RuntimeError("git cat-file batch response is truncated")
        header = raw[cursor:header_end].split(b" ")
        if len(header) != 3:
            raise RuntimeError("git cat-file batch response header is malformed")
        observed_oid, object_type, raw_size = header
        try:
            size = int(raw_size)
        except ValueError as exc:
            raise RuntimeError("git cat-file batch size is invalid") from exc
        if observed_oid.decode("ascii") != entry.oid or object_type != b"blob" or size < 0:
            raise RuntimeError("git cat-file batch identity does not match ls-tree authority")
        cursor = header_end + 1
        blob = raw[cursor:cursor + size]
        if len(blob) != size or raw[cursor + size:cursor + size + 1] != b"\n":
            raise RuntimeError("git cat-file batch blob is truncated")
        blobs.append(blob)
        cursor += size + 1
    if cursor != len(raw):
        raise RuntimeError("git cat-file batch emitted trailing unbound bytes")
    return tuple(blobs)


def _materialize_exact_source(sha: str, destination: Path) -> tuple[str, int]:
    entries = _git_tree_entries(sha)
    blobs = _git_blob_batch(entries)
    destination.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256()
    digest.update(_MATERIALIZATION_SCHEMA.encode("ascii") + b"\0")
    for entry, blob in zip(entries, blobs, strict=True):
        path_bytes = entry.path.encode("utf-8")
        digest.update(entry.mode.encode("ascii") + b"\0")
        digest.update(entry.oid.encode("ascii") + b"\0")
        digest.update(len(path_bytes).to_bytes(4, "big") + path_bytes)
        digest.update(len(blob).to_bytes(8, "big") + blob)
        target = destination.joinpath(*PurePosixPath(entry.path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise RuntimeError(f"tracked source path collision during materialization: {entry.path!r}")
        target.write_bytes(blob)
        target.chmod(0o755 if entry.mode == "100755" else 0o644)
    return digest.hexdigest(), len(entries)

def _build_distributions(
    output: Path, *, sha: str
) -> tuple[Path, Path, dict[str, object], ReleaseManifest]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(
        prefix="noetrium-release-source-", dir=_external_temp_parent()
    ) as td:
        source_root = Path(td) / "source"
        source_materialization_sha256, source_file_count = _materialize_exact_source(
            sha, source_root
        )
        manifest = build_release_manifest(source_root)
        argv = [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(output)]
        completed = subprocess.run(argv, cwd=source_root, text=True, capture_output=True, check=False)
        command = {
            "argv": argv,
            "cwd_mode": "external-git-object-database",
            "source_sha": sha,
            "source_materialization_schema": _MATERIALIZATION_SCHEMA,
            "source_materialization_sha256": source_materialization_sha256,
            "source_materialization_file_count": source_file_count,
            "returncode": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        }
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-4000:] or completed.stdout[-4000:] or "distribution build failed")
    wheels = tuple(output.glob("*.whl"))
    sdists = tuple(output.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("distribution build must produce exactly one wheel and one sdist")
    return wheels[0], sdists[0], command, manifest


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
    sha, branch = _require_clean_source()
    wheel, sdist, build_command, manifest = _build_distributions(output, sha=sha)
    oss_metadata = _verify_oss_metadata(wheel, sdist)
    _assert_source_identity(sha, branch)

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
    evidence = {
        "schema": "noetrium.distribution-release.v4",
        "manifest_source": "external-git-object-database",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "agent-noetrium-system",
        "branch": branch,
        "source_sha": sha,
        "source_tree_sha256": manifest.source_tree_sha256,
        "release_manifest_digest": manifest.digest(),
        "platform_version": manifest.platform_code_version,
        "python_requires": manifest.python_requires,
        "build_command": build_command,
        "oss_metadata": oss_metadata,
        "installed_verification": verification_refs,
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
    try:
        _assert_source_identity(sha, branch)
    except Exception:
        evidence_path.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = build_distribution_release(args.output)
    except Exception as exc:
        print(f"DISTRIBUTION_RELEASE_FAIL {type(exc).__qualname__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
