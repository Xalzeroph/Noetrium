from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes

from noetrium_platform.foundation.governance.release.api import FileDigest, ReleaseManifest


class ReleaseManifestDecodeError(ValueError):
    """A release-manifest document violates the release manifest contract."""


def encode_release_manifest(manifest: ReleaseManifest) -> bytes:
    return json.dumps(
        asdict(manifest),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8") + b"\n"


def decode_release_manifest(raw: bytes) -> ReleaseManifest:
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise TypeError("manifest must be object")
        files_raw = data["files"]
        if not isinstance(files_raw, list):
            raise TypeError("manifest files must be list")
        files = tuple(FileDigest(**row) for row in files_raw)
        return ReleaseManifest(
            schema_version=int(data["schema_version"]),
            files=files,
            source_tree_sha256=str(data["source_tree_sha256"]),
            python_requires=str(data["python_requires"]),
            platform_code_version=str(data["platform_code_version"]),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ReleaseManifestDecodeError("release manifest violates the manifest contract") from exc


def load_release_manifest(path: Path) -> ReleaseManifest:
    return decode_release_manifest(Path(path).read_bytes())


def write_release_manifest(path: Path, manifest: ReleaseManifest) -> None:
    atomic_replace_bytes(Path(path), encode_release_manifest(manifest))


__all__ = [
    "ReleaseManifestDecodeError",
    "decode_release_manifest",
    "encode_release_manifest",
    "load_release_manifest",
    "write_release_manifest",
]
