from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
from pathlib import Path
import tomllib

from noetrium_platform.foundation.kernel.kernel.durability import sha256_file


@dataclass(frozen=True, slots=True)
class InstalledPlatformIdentity:
    version: str
    artifact_sha256: str


def _source_checkout_identity() -> InstalledPlatformIdentity:
    root = Path(__file__).resolve().parents[4]
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeError("noetrium distribution metadata and source identity are unavailable")
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    version = str(project.get("version", "")).strip()
    if not version:
        raise RuntimeError("noetrium source project version is unavailable")
    digest = hashlib.sha256()
    observed = 0
    for relative_root in ("noetrium", "noetrium_platform"):
        source_root = root / relative_root
        if not source_root.is_dir():
            raise RuntimeError(f"noetrium source package is unavailable: {relative_root}")
        for path in sorted(source_root.rglob("*"), key=lambda row: row.relative_to(root).as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root).as_posix()
            if "__pycache__" in path.parts or relative.endswith((".pyc", ".pyo")):
                continue
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(sha256_file(path)[0]))
            digest.update(b"\0")
            observed += 1
    digest.update(b"pyproject.toml\0")
    digest.update(bytes.fromhex(sha256_file(pyproject)[0]))
    observed += 1
    if observed == 0:
        raise RuntimeError("noetrium source checkout contains no readable package files")
    return InstalledPlatformIdentity(version, digest.hexdigest())


def installed_platform_identity() -> InstalledPlatformIdentity:
    try:
        distribution = importlib.metadata.distribution("noetrium")
    except importlib.metadata.PackageNotFoundError:
        return _source_checkout_identity()
    version = str(distribution.version).strip()
    if not version:
        raise RuntimeError("noetrium distribution version is unavailable")
    files = tuple(distribution.files or ())
    if not files:
        raise RuntimeError("noetrium distribution file inventory is unavailable")
    digest = hashlib.sha256()
    observed = 0
    for entry in sorted(files, key=lambda row: str(row).replace("\\", "/")):
        relative = str(entry).replace("\\", "/")
        if not (
            relative.startswith(("noetrium/", "noetrium_platform/"))
            or (".dist-info/" in relative and relative.endswith("/METADATA"))
        ):
            continue
        path = Path(entry.locate())
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)[0]))
        digest.update(b"\0")
        observed += 1
    if observed == 0:
        raise RuntimeError("noetrium distribution contains no readable package files")
    return InstalledPlatformIdentity(version, digest.hexdigest())


__all__ = ["InstalledPlatformIdentity", "installed_platform_identity"]
