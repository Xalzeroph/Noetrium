from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import shutil
import tempfile

from noetrium_platform.foundation.governance.release.runtime.manifest import (
    build_release_manifest,
    verify_release_manifest,
)
from noetrium_platform.foundation.kernel.kernel import materialize_staged_bytes


_STABILITY_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class PlatformSourceSnapshot:
    root: Path
    source_tree_sha256: str
    manifest_digest: str
    file_count: int
    total_bytes: int


def _stable_manifest(root: Path):
    previous = None
    for _attempt in range(_STABILITY_ATTEMPTS):
        current = build_release_manifest(root)
        if previous is not None and (
            current.source_tree_sha256 == previous.source_tree_sha256
            and current.digest() == previous.digest()
        ):
            return current
        previous = current
    raise RuntimeError(
        "Noetrium platform source remained mutable while an immutable execution "
        "snapshot was being captured"
    )


def _verify_materialized(root: Path, manifest) -> None:
    observed = build_release_manifest(
        root,
        platform_code_version=manifest.platform_code_version,
        python_requires=manifest.python_requires,
    )
    errors = verify_release_manifest(root, manifest, actual_manifest=observed)
    if errors:
        raise RuntimeError(
            "materialized Noetrium platform source snapshot drifted: "
            + "; ".join(errors[:8])
        )
    if observed.digest() != manifest.digest():
        raise RuntimeError("materialized Noetrium platform manifest identity drifted")


def materialize_platform_source_snapshot(
    source_root: Path,
    snapshot_store: Path,
) -> PlatformSourceSnapshot:
    """Capture one immutable content-addressed platform source cut.

    The mutable workspace is read until two complete release manifests agree.
    Each selected file is then copied only after exact size/hash verification.
    The copied tree is independently re-manifested before an atomic rename makes
    it visible. Existing snapshots are always reverified before reuse.
    """

    source = Path(source_root).expanduser().resolve()
    store = Path(snapshot_store).expanduser().resolve()
    if source.is_symlink() or not source.is_dir():
        raise ValueError("platform source root must be a real directory")
    if store.exists() and (store.is_symlink() or not store.is_dir()):
        raise ValueError("platform source snapshot store must be a real directory")
    store.mkdir(parents=True, exist_ok=True)

    manifest = _stable_manifest(source)
    digest = manifest.source_tree_sha256
    target = store / digest
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise RuntimeError("platform source snapshot target has invalid identity")
        _verify_materialized(target, manifest)
        return PlatformSourceSnapshot(
            target,
            digest,
            manifest.digest(),
            len(manifest.files),
            sum(row.size for row in manifest.files),
        )

    temporary = Path(tempfile.mkdtemp(prefix=f".{digest[:16]}-", dir=store))
    try:
        for row in manifest.files:
            relative = Path(*row.path.split("/"))
            origin = source / relative
            if origin.is_symlink() or not origin.is_file():
                raise RuntimeError(
                    "platform source changed while snapshotting: " + row.path
                )
            payload = origin.read_bytes()
            if len(payload) != row.size or hashlib.sha256(payload).hexdigest() != row.sha256:
                raise RuntimeError(
                    "platform source changed while snapshotting: " + row.path
                )
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            materialize_staged_bytes(destination, payload)

        _verify_materialized(temporary, manifest)
        try:
            temporary.rename(target)
        except OSError:
            if target.is_symlink() or not target.is_dir():
                raise
            _verify_materialized(target, manifest)
        else:
            temporary = target
    finally:
        if temporary != target and temporary.exists():
            shutil.rmtree(temporary)

    return PlatformSourceSnapshot(
        target,
        digest,
        manifest.digest(),
        len(manifest.files),
        sum(row.size for row in manifest.files),
    )


__all__ = ["PlatformSourceSnapshot", "materialize_platform_source_snapshot"]
