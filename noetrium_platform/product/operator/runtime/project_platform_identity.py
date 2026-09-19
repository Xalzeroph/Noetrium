from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstalledPlatformIdentity:
    version: str
    artifact_sha256: str


def installed_platform_identity() -> InstalledPlatformIdentity:
    try:
        distribution = importlib.metadata.distribution("noetrium")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("noetrium distribution metadata is unavailable") from exc
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
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
        observed += 1
    if observed == 0:
        raise RuntimeError("noetrium distribution contains no readable package files")
    return InstalledPlatformIdentity(version, digest.hexdigest())


__all__ = ["InstalledPlatformIdentity", "installed_platform_identity"]
