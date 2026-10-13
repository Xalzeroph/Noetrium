from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_bytes, canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.kernel import InterprocessFileLock, atomic_replace_bytes

from ..api import MinecraftServerSpec
from .server_files import render_server_properties
from .world_copy import FilesystemMinecraftWorldCopier, MinecraftWorldCopier
from .world_cut_integrity import manifest_digest, tree_manifest

PRISTINE_WORLD_TEMPLATE_SCHEMA = "noetrium.minecraft-pristine-world-template.v1"
_DYNAMIC_SERVER_PROPERTIES = frozenset({
    "server-ip", "server-port", "enable-rcon", "rcon.password", "rcon.port",
})


def _generation_properties(spec: MinecraftServerSpec) -> tuple[tuple[str, str], ...]:
    rendered = render_server_properties(
        spec,
        rcon_password="template-provenance" if spec.rcon_endpoint is not None else None,
    )
    rows: list[tuple[str, str]] = []
    for line in rendered.splitlines():
        if not line:
            continue
        key, value = line.split("=", 1)
        if key not in _DYNAMIC_SERVER_PROPERTIES:
            rows.append((key, value))
    return tuple(sorted(rows))


def pristine_world_template_key(spec: MinecraftServerSpec, *, asset_digest: str) -> str:
    require_sha256(asset_digest, "Minecraft pristine template asset_digest")
    return canonical_digest({
        "schema": PRISTINE_WORLD_TEMPLATE_SCHEMA,
        "asset_digest": asset_digest,
        "world_properties": _generation_properties(spec),
    })


class MinecraftPristineWorldTemplateReservation:
    def __init__(self, cache, *, key: str, level_name: str, lock: InterprocessFileLock) -> None:
        self._cache = cache
        self.key = key
        self.level_name = level_name
        self._lock = lock
        self._closed = False
        self._published = False

    @property
    def published(self) -> bool:
        return self._published

    def publish(self, source_level: Path) -> str:
        if self._closed:
            raise RuntimeError("Minecraft pristine template reservation is closed")
        if not self._published:
            self._cache._publish_locked(self.key, self.level_name, source_level.resolve())
            self._published = True
        return self.key

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.__exit__(None, None, None)


class MinecraftPristineWorldTemplateCache:
    """Append-only pristine world cache with cross-process singleflight."""

    def __init__(self, root: str | Path, *, copier: MinecraftWorldCopier | None = None) -> None:
        self.root = Path(root).resolve()
        self.templates_root = self.root / "templates"
        self.metadata_root = self.root / "metadata"
        self.locks_root = self.root / "locks"
        for path in (self.templates_root, self.metadata_root, self.locks_root):
            path.mkdir(parents=True, exist_ok=True)
        self._copier = copier or FilesystemMinecraftWorldCopier()
        self._verified: dict[str, tuple[int, int, str]] = {}
        self._verified_lock = threading.Lock()

    def _metadata(self, key: str) -> Path:
        return self.metadata_root / f"{key}.json"

    def _resolve_current_locked(self, key: str, level_name: str) -> Path | None:
        metadata = self._metadata(key)
        if not metadata.is_file():
            return None
        try:
            marker_stat = metadata.stat()
            row = json.loads(metadata.read_text(encoding="utf-8"))
            if set(row) != {"schema", "template_key", "level_name", "manifest_digest", "template_name"}:
                return None
            if row["schema"] != PRISTINE_WORLD_TEMPLATE_SCHEMA or row["template_key"] != key or row["level_name"] != level_name:
                return None
            name = str(row["template_name"])
            if not name.startswith(key + ".") or "/" in name or "\\" in name:
                return None
            template = self.templates_root / name
            if not template.is_dir() or not (template / "level.dat").is_file():
                return None
            identity = (int(marker_stat.st_mtime_ns), int(marker_stat.st_size), name)
            with self._verified_lock:
                cached = self._verified.get(key)
            if cached == identity:
                return template
            if manifest_digest(tree_manifest(template)) != row["manifest_digest"]:
                return None
            with self._verified_lock:
                self._verified[key] = identity
            return template
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def prepare(self, spec: MinecraftServerSpec, *, asset_digest: str) -> MinecraftPristineWorldTemplateReservation | None:
        destination = Path(spec.workdir).resolve() / spec.level_name
        if destination.exists():
            return None
        key = pristine_world_template_key(spec, asset_digest=asset_digest)
        lock = InterprocessFileLock(self.locks_root / f"{key}.lock", blocking=True)
        lock.__enter__()
        try:
            template = self._resolve_current_locked(key, spec.level_name)
            if template is None:
                # A miss keeps the per-template lock in the reservation. Exactly
                # one producer may generate and publish the immutable generation.
                return MinecraftPristineWorldTemplateReservation(
                    self, key=key, level_name=spec.level_name, lock=lock
                )
        except BaseException:
            lock.__exit__(None, None, None)
            raise

        # Published generations are append-only. The lock protects only
        # selection/publication of the authoritative generation; it must not
        # serialize independent consumers while they copy an immutable tree.
        # Releasing here changes template-hit throughput from one world copy at
        # a time to filesystem-limited parallel copy without weakening truth.
        lock.__exit__(None, None, None)
        self._copier.copy(template, destination)
        return None

    def _publish_locked(self, key: str, level_name: str, source_level: Path) -> None:
        if not source_level.is_dir() or not (source_level / "level.dat").is_file():
            raise RuntimeError(
                f"Minecraft pristine template source is incomplete: {source_level}"
            )

        # The content digest is not known until the one-pass copy completes.
        # Copy to a non-authoritative pending generation in the same directory
        # so final rename is atomic and cannot cross filesystems.
        pending_name = (
            f".{key}.pending.{os.getpid()}."
            f"{threading.get_ident()}.{time.time_ns()}"
        )
        pending = self.templates_root / pending_name
        try:
            copied_manifest = self._copier.copy_with_manifest(
                source_level,
                pending,
            )
            digest = manifest_digest(copied_manifest)
            base_name = f"{key}.{digest}"
            template = self.templates_root / base_name
            if template.exists():
                # Preserve any pre-existing generation as crash evidence rather
                # than overwriting an inode that a concurrent reader may hold.
                base_name = (
                    f"{base_name}.{os.getpid()}."
                    f"{threading.get_ident()}.{time.time_ns()}"
                )
                template = self.templates_root / base_name
            pending.rename(template)
        except BaseException:
            if pending.exists():
                import shutil
                shutil.rmtree(pending, ignore_errors=True)
            raise

        marker = {
            "schema": PRISTINE_WORLD_TEMPLATE_SCHEMA,
            "template_key": key,
            "level_name": level_name,
            "manifest_digest": digest,
            "template_name": base_name,
        }
        atomic_replace_bytes(self._metadata(key), canonical_bytes(marker))
        stat = self._metadata(key).stat()
        with self._verified_lock:
            self._verified[key] = (
                int(stat.st_mtime_ns),
                int(stat.st_size),
                base_name,
            )


__all__ = [
    "MinecraftPristineWorldTemplateCache",
    "PRISTINE_WORLD_TEMPLATE_SCHEMA",
    "MinecraftPristineWorldTemplateReservation",
    "pristine_world_template_key",
]
