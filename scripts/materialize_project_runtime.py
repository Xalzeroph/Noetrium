from __future__ import annotations

import argparse
import fcntl
import hashlib
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib
from urllib.parse import urlparse

_SCHEMA = "noetrium.project-runtime-lock"
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _project_document(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("project runtime materialization requires a real pyproject.toml")
    return tomllib.loads(path.read_text("utf-8"))


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dependency_name(requirement: str) -> str:
    match = _NAME.match(requirement)
    if match is None:
        raise RuntimeError("invalid project dependency requirement: " + requirement)
    return _canonical_name(match.group(1))


def _installed_constraints() -> tuple[str, ...]:
    rows: dict[str, str] = {}
    for distribution in importlib_metadata.distributions():
        name = str(distribution.metadata.get("Name", "")).strip()
        version = str(distribution.version).strip()
        if not name or not version:
            continue
        canonical_name = _canonical_name(name)
        row = f"{name}=={version}"
        previous = rows.get(canonical_name)
        if previous is not None and previous != row:
            raise RuntimeError(
                f"base runtime exposes multiple installed identities for {name}"
            )
        rows[canonical_name] = row
    return tuple(rows[name] for name in sorted(rows))


def _project_dependencies(
    project_root: Path,
    platform_root: Path,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    project_doc = _project_document(project_root)
    platform_doc = _project_document(platform_root)

    project = project_doc.get("project")
    platform = platform_doc.get("project")
    if not isinstance(project, dict) or not isinstance(platform, dict):
        raise RuntimeError("project metadata is incomplete")

    platform_version = str(platform.get("version", "")).strip()
    if not platform_version:
        raise RuntimeError("platform version is missing")

    raw_project_dependencies = project.get("dependencies", ())
    raw_platform_dependencies = platform.get("dependencies", ())
    if not isinstance(raw_project_dependencies, list):
        raise RuntimeError("project dependencies must be an array")
    if not isinstance(raw_platform_dependencies, list):
        raise RuntimeError("platform dependencies must be an array")

    project_dependencies = tuple(str(item).strip() for item in raw_project_dependencies)
    if any(not item for item in project_dependencies):
        raise RuntimeError("project dependencies must not contain empty requirements")

    noetrium_rows = tuple(
        item for item in project_dependencies if _dependency_name(item) == "noetrium"
    )
    expected = f"noetrium=={platform_version}"
    if len(noetrium_rows) != 1 or re.sub(r"\s+", "", noetrium_rows[0]).lower() != expected.lower():
        raise RuntimeError(
            "project must contain exactly one exact platform pin: " + expected
        )

    extras = tuple(
        item for item in project_dependencies if _dependency_name(item) != "noetrium"
    )
    platform_dependencies = tuple(str(item).strip() for item in raw_platform_dependencies)
    return platform_version, extras, platform_dependencies


def _validated_existing_lock(
    path: Path,
    *,
    declaration_digest: str,
    python_version: str,
    base_image_id: str,
) -> dict | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        row = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(row, dict):
        return None
    if row.get("schema") != _SCHEMA:
        return None
    if row.get("declaration_digest") != declaration_digest:
        return None
    if row.get("python_version") != python_version:
        return None
    if row.get("base_image_id") != base_image_id:
        return None
    expected = row.get("lock_digest")
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        return None
    payload = dict(row)
    payload.pop("lock_digest", None)
    if _digest(payload) != expected:
        return None
    packages = row.get("packages")
    if not isinstance(packages, list) or not packages:
        return None
    return row


def _resolve(
    requirements: tuple[str, ...],
    *,
    base_constraints: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    with tempfile.TemporaryDirectory(prefix="noetrium-project-resolve-") as tmp:
        report = Path(tmp) / "pip-report.json"
        constraints = Path(tmp) / "base-constraints.txt"
        constraints.write_text("\n".join(base_constraints) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--no-input",
            "--report",
            str(report),
            "--constraint",
            str(constraints),
            "--only-binary=:all:",
            *requirements,
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                "project dependency closure resolution failed: " + detail[-4000:]
            )
        try:
            document = json.loads(report.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("pip did not emit a valid dependency report") from exc

    install = document.get("install")
    if not isinstance(install, list) or not install:
        raise RuntimeError("project dependency resolver returned an empty closure")

    rows: dict[str, dict[str, str]] = {}
    for item in install:
        if not isinstance(item, dict):
            raise RuntimeError("project dependency report contains an invalid row")
        metadata = item.get("metadata")
        download = item.get("download_info")
        if not isinstance(metadata, dict) or not isinstance(download, dict):
            raise RuntimeError("project dependency report lacks package provenance")
        name = str(metadata.get("name", "")).strip()
        version = str(metadata.get("version", "")).strip()
        if not name or not version:
            raise RuntimeError("project dependency report lacks package identity")
        canonical_name = _canonical_name(name)

        url = str(download.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError(
                f"project dependency {name} is not backed by an immutable remote artifact"
            )
        archive = download.get("archive_info")
        hashes = archive.get("hashes") if isinstance(archive, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256.lower()):
            raise RuntimeError(
                f"project dependency {name} has no SHA-256 artifact proof"
            )
        row = {
            "name": name,
            "canonical_name": canonical_name,
            "version": version,
            "sha256": sha256.lower(),
        }
        previous = rows.get(canonical_name)
        if previous is not None and previous != row:
            raise RuntimeError(
                f"project dependency closure resolved multiple identities for {name}"
            )
        rows[canonical_name] = row

    return tuple(rows[name] for name in sorted(rows))


def _lock_lines(packages: list[dict[str, str]] | tuple[dict[str, str], ...]) -> str:
    lines = [
        f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}"
        for row in packages
    ]
    return "\n".join(lines) + "\n"


def _materialize_build_context(
    state_root: Path,
    *,
    base_image_id: str,
    lock: dict,
    recipe: bytes,
) -> str:
    lock_digest = str(lock["lock_digest"])
    recipe_sha256 = hashlib.sha256(recipe).hexdigest()
    runtime_key = _digest(
        {
            "schema": "noetrium.project-runtime-image",
            "base_image_id": base_image_id,
            "lock_digest": lock_digest,
            "recipe_sha256": recipe_sha256,
        }
    )
    target = state_root / "project-runtime" / "objects" / runtime_key
    target.mkdir(parents=True, exist_ok=True)

    requirements = _lock_lines(lock["packages"]).encode("utf-8")
    _atomic_write(target / "requirements.lock", requirements)
    _atomic_write(target / "Dockerfile", recipe)
    resolution = {
        "schema": "noetrium.project-runtime-materialization",
        "runtime_key": runtime_key,
        "base_image_id": base_image_id,
        "lock_digest": lock_digest,
        "requirements_sha256": hashlib.sha256(requirements).hexdigest(),
        "recipe_sha256": recipe_sha256,
    }
    _atomic_write(
        target / "materialization.json",
        _canonical(resolution) + b"\n",
    )
    return runtime_key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--platform-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--base-image-id", required=True)
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    platform_root = args.platform_root.resolve()
    state_root = args.state_root.resolve()
    if project_root.is_symlink() or platform_root.is_symlink():
        raise RuntimeError("project runtime roots must not be symlinks")
    if not args.base_image_id.startswith("sha256:"):
        raise RuntimeError("base image identity must be an immutable SHA-256 image id")

    platform_version, extras, platform_dependencies = _project_dependencies(
        project_root,
        platform_root,
    )
    recipe_path = platform_root / "deploy" / "bootstrap" / "ProjectRuntime.Dockerfile"
    if not recipe_path.is_file() or recipe_path.is_symlink():
        raise RuntimeError(
            "project runtime materialization requires the canonical ProjectRuntime.Dockerfile"
        )
    recipe = recipe_path.read_bytes()
    if not recipe:
        raise RuntimeError("canonical ProjectRuntime.Dockerfile must not be empty")
    if not extras:
        print("base")
        return 0

    state_root.mkdir(parents=True, exist_ok=True)
    base_constraints = _installed_constraints()
    if not base_constraints:
        raise RuntimeError("base runtime exposes no installed Python distribution inventory")
    base_python_environment_digest = _digest(base_constraints)
    lock_path = project_root / "project.dependencies.lock.json"
    lock_file = state_root / "project-runtime" / "materialize.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    python_version = ".".join(str(item) for item in sys.version_info[:3])
    declaration = {
        "schema": "noetrium.project-runtime-declaration",
        "platform_version": platform_version,
        "python_version": python_version,
        "base_image_id": args.base_image_id,
        "base_python_environment_digest": base_python_environment_digest,
        "platform_dependencies": tuple(sorted(platform_dependencies)),
        "project_dependencies": tuple(sorted(extras)),
    }
    declaration_digest = _digest(declaration)

    with lock_file.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        current = _validated_existing_lock(
            lock_path,
            declaration_digest=declaration_digest,
            python_version=python_version,
            base_image_id=args.base_image_id,
        )
        if current is None:
            packages = _resolve(
                tuple(platform_dependencies) + tuple(extras),
                base_constraints=base_constraints,
            )
            payload = {
                "schema": _SCHEMA,
                "platform_version": platform_version,
                "python_version": python_version,
                "base_image_id": args.base_image_id,
                "base_python_environment_digest": base_python_environment_digest,
                "declaration_digest": declaration_digest,
                "platform_dependencies": list(sorted(platform_dependencies)),
                "project_dependencies": list(sorted(extras)),
                "packages": list(packages),
            }
            payload["lock_digest"] = _digest(payload)
            _atomic_write(lock_path, _canonical(payload) + b"\n")
            current = payload

        runtime_key = _materialize_build_context(
            state_root,
            base_image_id=args.base_image_id,
            lock=current,
            recipe=recipe,
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    print(runtime_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
