"""Official Noetrium release workflow exposed through ``noetrium dev release``."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv

from .runtime.manifest import build_release_manifest
from .runtime.project_metadata import load_project_metadata
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

_DEFAULT_ROOT = Path(__file__).resolve().parents[4]
_RELEASE_EVIDENCE = "DISTRIBUTION_RELEASE_EVIDENCE.json"
_CONTAINER_RELEASE_EVIDENCE = "CONTAINER_RELEASE_EVIDENCE.json"
_CONTAINER_VERIFICATION = "CONTAINER_VERIFICATION.json"
_RUNTIME_PLATFORM = "linux/amd64"
_PYTHON_RUNTIME_IMAGE = "python:3.12-slim-bookworm"


_SECURITY_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "machine_mount": re.compile(rb"/data/hdd[0-9]+/|(?i:[A-Z]:\\Users\\[^\\\r\n]+)"),
}


def _source_security_scan(root: Path, manifest) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    for item in manifest.files:
        path = root / item.path
        if item.size > 8_000_000:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue
        for code, pattern in _SECURITY_PATTERNS.items():
            if pattern.search(raw):
                findings.append({"code": code, "path": item.path})
    if findings:
        summary = "; ".join(f"{row['code']}:{row['path']}" for row in findings[:12])
        raise RuntimeError(f"release source security scan failed: {summary}")
    return {"clean": True, "scanned_files": len(manifest.files), "findings": 0}


def _run(
    argv: list[str],
    *,
    cwd: Path,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()
        raise RuntimeError(f"{' '.join(argv)} failed: {detail}")
    return completed


def _git(root: Path, *args: str, check: bool = True) -> str:
    return (_run(["git", *args], cwd=root, check=check).stdout or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_git(root: Path) -> tuple[bool, tuple[str, ...]]:
    rows = tuple(row for row in _git(root, "status", "--porcelain=v1").splitlines() if row)
    return not rows, rows


def _read_citation_version(root: Path) -> str | None:
    path = root / "CITATION.cff"
    if not path.is_file():
        return None
    match = re.search(r"(?m)^version:\s*[\"']?([^\"'\s]+)", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _read_lock_version(root: Path) -> str | None:
    path = root / "uv.lock"
    if not path.is_file():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    for package in data.get("package", []):
        if package.get("name") == "noetrium":
            return str(package.get("version") or "") or None
    return None


def _version_status(root: Path, expected: str | None) -> dict[str, object]:
    metadata = load_project_metadata(root, allow_unversioned=False)
    values = {
        "pyproject": metadata.version,
        "citation": _read_citation_version(root),
        "uv_lock": _read_lock_version(root),
    }
    target = expected or metadata.version
    mismatches = {key: value for key, value in values.items() if value is not None and value != target}
    if metadata.version != target:
        mismatches["pyproject"] = metadata.version
    return {"target": target, "values": values, "clean": not mismatches, "mismatches": mismatches}


def _release_output(root: Path, version: str, explicit: str | None) -> Path:
    return Path(explicit).expanduser().resolve() if explicit else root.parent / f"noetrium-{version}-dist"


def _runner_python(root: Path) -> Path:
    if importlib.util.find_spec("build") is not None:
        return Path(sys.executable)
    runner = root / ".noetrium" / "release-tooling" / f"py{sys.version_info.major}{sys.version_info.minor}"
    python = runner / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        runner.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=True).create(runner)
    probe = _run([str(python), "-c", "import build"], cwd=root, check=False)
    if probe.returncode != 0:
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "build>=1.2,<2",
            ],
            cwd=root,
            capture=False,
        )
    return python


def _prepare(root: Path, expected: str | None) -> dict[str, object]:
    version = _version_status(root, expected)
    if not version["clean"]:
        raise RuntimeError(f"release version authorities disagree: {version['mismatches']}")
    generator = root / "scripts" / "update_generated_docs.py"
    if not generator.is_file():
        raise RuntimeError("source checkout is missing scripts/update_generated_docs.py")
    # A formal release never mutates its source authority. Generated projections
    # must already be current in the committed source cut; drift fails closed.
    _run([sys.executable, str(generator), "--check", "--root", str(root)], cwd=root, capture=False)
    manifest = build_release_manifest(root)
    security = _source_security_scan(root, manifest)
    return {
        "phase": "prepare",
        "version": manifest.platform_code_version,
        "source_tree_sha256": manifest.source_tree_sha256,
        "file_count": len(manifest.files),
        "source_security": security,
    }


def _docker_image_metadata(root: Path, image: str) -> dict[str, object]:
    completed = _run(["docker", "image", "inspect", image], cwd=root)
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError(f"invalid Docker image metadata for {image}")
    return rows[0]


def _require_linux_amd64_docker(root: Path) -> dict[str, str]:
    completed = _run(
        ["docker", "version", "--format", "{{.Server.Os}} {{.Server.Arch}} {{.Server.Version}}"],
        cwd=root,
    )
    fields = completed.stdout.strip().split()
    if len(fields) != 3:
        raise RuntimeError("Docker server did not report OS/architecture/version")
    os_name, arch, version = fields
    if (os_name, arch) != ("linux", "amd64"):
        raise RuntimeError(
            f"Noetrium v1 runtime release requires Linux/amd64 Docker, got {os_name}/{arch}"
        )
    return {"os": os_name, "arch": arch, "version": version}


def _resolve_python_runtime(root: Path) -> tuple[str, str]:
    """Resolve the Linux base image to an immutable local content identity.

    A formal release must not contact a registry merely to refresh a mutable tag.
    Reuse an already-present qualified base image; pull only when the declared tag
    is absent, then bind the build to its exact repository digest and image ID.
    """

    inspected = _run(
        ["docker", "image", "inspect", _PYTHON_RUNTIME_IMAGE],
        cwd=root,
        check=False,
    )
    if inspected.returncode != 0:
        _run(["docker", "pull", _PYTHON_RUNTIME_IMAGE], cwd=root, capture=False)
    metadata = _docker_image_metadata(root, _PYTHON_RUNTIME_IMAGE)
    if metadata.get("Os") != "linux" or metadata.get("Architecture") != "amd64":
        raise RuntimeError("Python runtime base is not Linux/amd64")
    image_id = str(metadata.get("Id") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("Python runtime image is not content-addressed")
    repo_digests = metadata.get("RepoDigests")
    if not isinstance(repo_digests, list):
        repo_digests = []
    immutable = next(
        (str(value) for value in repo_digests if isinstance(value, str) and value.startswith("python@sha256:")),
        None,
    )
    if immutable is None:
        immutable = next(
            (str(value) for value in repo_digests if isinstance(value, str) and "@sha256:" in value),
            None,
        )
    if immutable is None:
        raise RuntimeError("Python runtime image has no immutable repository digest")
    return immutable, image_id.removeprefix("sha256:")


def _write_json(path: Path, payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    atomic_replace_bytes(path, raw)
    return hashlib.sha256(raw).hexdigest()


def _write_release_checksums(output: Path) -> Path:
    names = [
        name
        for name in (
            "DISTRIBUTION_RELEASE_EVIDENCE.json",
            "DISTRIBUTION_RELEASE_EVIDENCE.json.sha256",
            "RUNTIME_ARTIFACT_EVIDENCE.json",
            "RUNTIME_ARTIFACT_EVIDENCE.json.sha256",
            "SBOM.spdx.json",
            "SHA256SUMS",
            "wheel-installed-verification.json",
            "sdist-installed-verification.json",
            _CONTAINER_VERIFICATION,
            _CONTAINER_RELEASE_EVIDENCE,
            f"{_CONTAINER_RELEASE_EVIDENCE}.sha256",
        )
        if (output / name).is_file()
    ]
    names += sorted(
        path.name
        for path in output.iterdir()
        if path.is_file() and path.name.startswith("noetrium-") and path.suffix in {".whl", ".gz", ".tar"}
    )
    path = output / "RELEASE_SHA256SUMS"
    payload = "".join(
        f"{_sha256(output / name)}  {name}\n" for name in dict.fromkeys(names)
    ).encode("utf-8")
    atomic_replace_bytes(path, payload)
    return path


def _build(root: Path, expected: str | None, output_arg: str | None) -> dict[str, object]:
    version = _version_status(root, expected)
    if not version["clean"]:
        raise RuntimeError(f"release version authorities disagree: {version['mismatches']}")
    target = str(version["target"])
    output = _release_output(root, target, output_arg)
    if output == root or root in output.parents:
        raise RuntimeError("release output must be outside the source tree")
    docker = _require_linux_amd64_docker(root)
    script = root / "scripts" / "release_distribution.py"
    if not script.is_file():
        raise RuntimeError("source checkout is missing scripts/release_distribution.py")
    runner = _runner_python(root)
    completed = _run([str(runner), str(script), str(output)], cwd=root)
    distribution = json.loads(completed.stdout)
    current = build_release_manifest(root)
    source_sha = str(distribution.get("source_sha") or "")
    if source_sha != current.source_tree_sha256:
        raise RuntimeError("distribution was not built from the current canonical source cut")

    runtime_evidence = json.loads((output / "RUNTIME_ARTIFACT_EVIDENCE.json").read_text(encoding="utf-8"))
    wheel_rows = runtime_evidence.get("artifacts", {})
    wheel_names = [name for name in wheel_rows if isinstance(name, str) and name.endswith(".whl")]
    if len(wheel_names) != 1:
        raise RuntimeError("runtime artifact evidence must bind exactly one wheel")
    wheel_sha = str(wheel_rows[wheel_names[0]]["sha256"])
    runtime_projection_sha = str(runtime_evidence["source_tree_sha256"])

    context = output / "container-context"
    context_script = root / "scripts" / "prepare_container_context.py"
    context_result = _run(
        [
            sys.executable,
            str(context_script),
            str(output),
            str(context),
            "--expected-source-sha",
            source_sha,
        ],
        cwd=root,
    )
    context_receipt = json.loads(context_result.stdout)
    runtime_evidence_sha = str(context_receipt["distribution_evidence_sha256"])

    python_runtime_ref, python_runtime_sha = _resolve_python_runtime(root)

    image = f"noetrium:{target}-{source_sha[:12]}"
    _run(
        [
            "docker", "build",
            "--platform", _RUNTIME_PLATFORM,
            "--build-arg", f"PYTHON_RUNTIME_IMAGE={python_runtime_ref}",
            "--build-arg", f"PLATFORM_PYTHON_RUNTIME_IDENTITY_DIGEST={python_runtime_sha}",
            "--build-arg", f"PLATFORM_SOURCE_SHA={source_sha}",
            "--build-arg", f"PLATFORM_RUNTIME_PROJECTION_SHA256={runtime_projection_sha}",
            "--build-arg", f"PLATFORM_WHEEL_SHA256={wheel_sha}",
            "--build-arg", f"PLATFORM_DISTRIBUTION_EVIDENCE_SHA256={runtime_evidence_sha}",
            "--tag", image,
            str(context),
        ],
        cwd=root,
        capture=False,
    )

    verification_path = output / _CONTAINER_VERIFICATION
    verify_script = root / "scripts" / "verify_container_image.py"
    _run(
        [
            sys.executable,
            str(verify_script),
            image,
            "--expected-source-sha", source_sha,
            "--expected-wheel-sha256", wheel_sha,
            "--expected-distribution-evidence-sha256", runtime_evidence_sha,
            "--expected-python-runtime-identity-digest", python_runtime_sha,
            "--output", str(verification_path),
        ],
        cwd=root,
        capture=False,
    )
    image_meta = _docker_image_metadata(root, image)
    if image_meta.get("Os") != "linux" or image_meta.get("Architecture") != "amd64":
        raise RuntimeError("qualified runtime image is not Linux/amd64")
    image_id = str(image_meta.get("Id") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError("qualified runtime image has no content-addressed image ID")

    archive = output / f"noetrium-{target}-linux-amd64-image.tar"
    _run(["docker", "image", "save", "-o", str(archive), image], cwd=root, capture=False)
    verification_sha = _sha256(verification_path)
    container_evidence = {
        "schema": "noetrium.container-release.v1",
        "runtime_authority": "linux-docker-image",
        "runtime_platform": _RUNTIME_PLATFORM,
        "version": target,
        "source_sha": source_sha,
        "runtime_projection_sha256": runtime_projection_sha,
        "wheel_sha256": wheel_sha,
        "runtime_artifact_evidence_sha256": runtime_evidence_sha,
        "python_runtime_image": _PYTHON_RUNTIME_IMAGE,
        "python_runtime_immutable_ref": python_runtime_ref,
        "python_runtime_identity_digest": python_runtime_sha,
        "image": image,
        "image_id": image_id,
        "image_archive": archive.name,
        "image_archive_sha256": _sha256(archive),
        "container_verification": verification_path.name,
        "container_verification_sha256": verification_sha,
        "docker_server": docker,
    }
    container_evidence_path = output / _CONTAINER_RELEASE_EVIDENCE
    container_evidence_sha = _write_json(container_evidence_path, container_evidence)
    atomic_replace_bytes(
        output / f"{_CONTAINER_RELEASE_EVIDENCE}.sha256",
        f"{container_evidence_sha}  {container_evidence_path.name}\n".encode("utf-8"),
    )
    checksums = _write_release_checksums(output)
    return {
        "phase": "build",
        "version": target,
        "runtime_authority": "linux-docker-image",
        "runtime_platform": _RUNTIME_PLATFORM,
        "output": str(output),
        "source_sha": source_sha,
        "runtime_projection_sha256": runtime_projection_sha,
        "image": image,
        "image_id": image_id,
        "image_archive": archive.name,
        "image_archive_sha256": container_evidence["image_archive_sha256"],
        "wheel": wheel_names[0],
        "wheel_sha256": wheel_sha,
        "release_checksums": checksums.name,
    }


def _verify(root: Path, expected: str | None, output_arg: str | None) -> dict[str, object]:
    version = _version_status(root, expected)
    if not version["clean"]:
        raise RuntimeError(f"release version authorities disagree: {version['mismatches']}")
    target = str(version["target"])
    output = _release_output(root, target, output_arg)
    evidence_path = output / _RELEASE_EVIDENCE
    container_path = output / _CONTAINER_RELEASE_EVIDENCE
    if not evidence_path.is_file() or not container_path.is_file():
        raise RuntimeError("distribution/container release evidence is missing")
    distribution = json.loads(evidence_path.read_text(encoding="utf-8"))
    container = json.loads(container_path.read_text(encoding="utf-8"))
    current = build_release_manifest(root)
    errors: list[str] = []
    if distribution.get("platform_version") != target:
        errors.append("artifact version differs from current release authority")
    if distribution.get("source_sha") != current.source_tree_sha256:
        errors.append("artifact source identity differs from current canonical source cut")
    if container.get("version") != target or container.get("source_sha") != current.source_tree_sha256:
        errors.append("container release identity differs from current source/version")
    if container.get("runtime_authority") != "linux-docker-image" or container.get("runtime_platform") != _RUNTIME_PLATFORM:
        errors.append("container release is not the canonical Linux/amd64 runtime")
    for name, metadata in distribution.get("artifacts", {}).items():
        path = output / name
        if not path.is_file():
            errors.append(f"artifact missing: {name}")
            continue
        if _sha256(path) != metadata.get("sha256"):
            errors.append(f"artifact digest mismatch: {name}")
    archive = output / str(container.get("image_archive") or "")
    if not archive.is_file() or _sha256(archive) != container.get("image_archive_sha256"):
        errors.append("Linux runtime image archive digest mismatch")
    sidecar = output / f"{_CONTAINER_RELEASE_EVIDENCE}.sha256"
    if not sidecar.is_file() or sidecar.read_text(encoding="utf-8").split()[0] != _sha256(container_path):
        errors.append("container release evidence sidecar mismatch")
    if errors:
        raise RuntimeError("; ".join(errors))

    _require_linux_amd64_docker(root)
    image = str(container["image"])
    inspect = _run(["docker", "image", "inspect", image], cwd=root, check=False)
    if inspect.returncode != 0:
        _run(["docker", "image", "load", "-i", str(archive)], cwd=root, capture=False)
    image_meta = _docker_image_metadata(root, image)
    if image_meta.get("Id") != container.get("image_id"):
        raise RuntimeError("loaded Docker image identity differs from release evidence")
    verify_script = root / "scripts" / "verify_container_image.py"
    verification_path = output / _CONTAINER_VERIFICATION
    _run(
        [
            sys.executable,
            str(verify_script),
            image,
            "--expected-source-sha", current.source_tree_sha256,
            "--expected-wheel-sha256", str(container["wheel_sha256"]),
            "--expected-distribution-evidence-sha256", str(container["runtime_artifact_evidence_sha256"]),
            "--expected-python-runtime-identity-digest", str(container["python_runtime_identity_digest"]),
            "--output", str(verification_path),
        ],
        cwd=root,
        capture=False,
    )
    _write_release_checksums(output)
    return {
        "phase": "verify",
        "version": target,
        "runtime_authority": "linux-docker-image",
        "runtime_platform": _RUNTIME_PLATFORM,
        "output": str(output),
        "source_sha": current.source_tree_sha256,
        "image": image,
        "image_id": container["image_id"],
        "image_archive": archive.name,
        "clean": True,
    }


def _github_repo(root: Path, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    remote = _git(root, "remote", "get-url", "origin", check=False)
    if not remote:
        return None
    match = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote)
    return match.group(1) if match else None


def _publish(
    root: Path,
    expected: str | None,
    output_arg: str | None,
    *,
    repo: str | None,
    notes_file: str | None,
) -> dict[str, object]:
    verified = _verify(root, expected, output_arg)
    clean, rows = _clean_git(root)
    if not clean:
        preview = "; ".join(rows[:8])
        raise RuntimeError(f"Git worktree must be clean before publication: {preview}")
    version = str(verified["version"])
    tag = f"v{version}"
    branch = _git(root, "branch", "--show-current")
    if not branch:
        raise RuntimeError("release publication requires a named Git branch")
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI 'gh' is required for GitHub Release publication")
    _run(["gh", "auth", "status"], cwd=root)
    resolved_repo = _github_repo(root, repo)
    if not resolved_repo:
        raise RuntimeError("cannot infer GitHub repository; pass --repo OWNER/NAME")
    existing = _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False)
    head = _git(root, "rev-parse", "HEAD")
    if existing and existing != head:
        raise RuntimeError(f"tag {tag} already exists at another commit")
    if not existing:
        _git(root, "tag", "-a", tag, "-m", f"Noetrium {tag}")
    try:
        _git(root, "push", "origin", branch)
        _git(root, "push", "origin", tag)
        output = Path(str(verified["output"]))
        assets = [
            path
            for path in sorted(output.iterdir())
            if path.is_file()
            and (
                path.suffix in {".whl", ".gz", ".tar"}
                or path.name in {"SBOM.spdx.json", "SHA256SUMS", "RELEASE_SHA256SUMS", _CONTAINER_VERIFICATION}
                or path.name.endswith("EVIDENCE.json")
                or path.name.endswith("EVIDENCE.json.sha256")
                or path.name.endswith("installed-verification.json")
            )
        ]
        argv = ["gh", "release", "create", tag, "--repo", resolved_repo, "--title", f"Noetrium {tag}"]
        if notes_file:
            argv += ["--notes-file", str(Path(notes_file).expanduser().resolve())]
        else:
            argv += ["--generate-notes"]
        argv += [str(path) for path in assets]
        _run(argv, cwd=root, capture=False)
    except Exception:
        # A local tag created by this command is safe to roll back when no remote
        # release was completed. Remote mutations are intentionally not guessed at.
        if not existing:
            remote_tag = _git(root, "ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
            if not remote_tag:
                _git(root, "tag", "-d", tag, check=False)
        raise
    return {
        "phase": "publish",
        "version": version,
        "tag": tag,
        "repository": resolved_repo,
        "commit": head,
        "output": verified["output"],
    }


def _status(root: Path, expected: str | None, output_arg: str | None) -> dict[str, object]:
    version = _version_status(root, expected)
    target = str(version["target"])
    output = _release_output(root, target, output_arg)
    clean, rows = _clean_git(root)
    manifest = build_release_manifest(root)
    return {
        "phase": "status",
        "version": version,
        "git": {
            "head": _git(root, "rev-parse", "HEAD", check=False) or None,
            "branch": _git(root, "branch", "--show-current", check=False) or None,
            "clean": clean,
            "changes": rows,
        },
        "source_tree_sha256": manifest.source_tree_sha256,
        "file_count": len(manifest.files),
        "output": str(output),
        "distribution_evidence_present": (output / _RELEASE_EVIDENCE).is_file(),
        "container_evidence_present": (output / _CONTAINER_RELEASE_EVIDENCE).is_file(),
        "runtime_authority": "linux-docker-image",
        "runtime_platform": _RUNTIME_PLATFORM,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noetrium dev release",
        description="Prepare, build, verify and publish one exact Linux Docker Noetrium release.",
    )
    parser.add_argument("action", nargs="?", choices=("status", "prepare", "build", "verify", "publish"))
    parser.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--version", help="expected release version; pyproject.toml remains authoritative")
    parser.add_argument("--output", help="artifact directory; defaults outside the source tree")
    parser.add_argument("--repo", help="GitHub OWNER/NAME; inferred from origin by default")
    parser.add_argument("--notes-file", help="release notes file passed to GitHub Release")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="one-shot prepare + build + verify + GitHub publish",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.publish and args.action not in (None, "publish"):
            raise ValueError("--publish cannot be combined with another release phase")
        action = "publish" if args.publish else (args.action or "status")
        if action == "status":
            result = _status(root, args.version, args.output)
        elif action == "prepare":
            result = _prepare(root, args.version)
        elif action == "build":
            result = _build(root, args.version, args.output)
        elif action == "verify":
            result = _verify(root, args.version, args.output)
        else:
            _prepare(root, args.version)
            _build(root, args.version, args.output)
            result = _publish(
                root,
                args.version,
                args.output,
                repo=args.repo,
                notes_file=args.notes_file,
            )
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"RELEASE_FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        for key, value in result.items():
            if isinstance(value, (dict, list, tuple)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
