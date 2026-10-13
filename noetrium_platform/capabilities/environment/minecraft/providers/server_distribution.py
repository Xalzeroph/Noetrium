from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from zipfile import ZipFile

from noetrium_platform.foundation.kernel.kernel.durability import durable_replace_directory

from noetrium_platform.foundation.kernel.kernel import (
    InterprocessFileLock,
    atomic_replace_bytes,
    canonical_bytes,
    canonical_digest,
    require_sha256,
)

SERVER_RUNTIME_DISTRIBUTION_SCHEMA = "noetrium.minecraft-server-runtime-distribution.v1"


@dataclass(frozen=True, slots=True)
class MinecraftServerRuntimeDistribution:
    key: str
    server_jar: Path
    libraries_dir: Path

    def __post_init__(self) -> None:
        require_sha256(self.key, "Minecraft server runtime distribution key")
        if not self.server_jar.is_file():
            raise FileNotFoundError(self.server_jar)
        if not self.libraries_dir.is_dir():
            raise FileNotFoundError(self.libraries_dir)


class MinecraftServerRuntimeDistributionCache:
    """Content-addressed extraction of immutable Mojang server runtime jars.

    Assignment worlds/configuration remain private. Only bundler-embedded
    immutable code artifacts are shared. The Mojang manifest SHA-256 values are
    verified before atomic publication and one interprocess lock serializes a
    cold producer for each exact server asset generation.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.distributions = self.root / "distributions"
        self.metadata = self.root / "metadata"
        self.locks = self.root / "locks"
        for path in (self.distributions, self.metadata, self.locks):
            path.mkdir(parents=True, exist_ok=True)
        self._verified: dict[str, tuple[int, int]] = {}
        self._verified_lock = threading.Lock()

    @staticmethod
    def _rows(raw: bytes, *, field: str) -> tuple[tuple[str, str, str], ...]:
        rows: list[tuple[str, str, str]] = []
        for line in raw.decode("utf-8", errors="strict").splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                raise RuntimeError(f"Minecraft bundler {field} row is malformed")
            digest, identity, relative = parts
            require_sha256(digest, f"Minecraft bundler {field} digest")
            rel = Path(relative)
            if rel.is_absolute() or ".." in rel.parts or not rel.parts:
                raise RuntimeError(f"Minecraft bundler {field} path escaped root")
            rows.append((digest, identity, relative))
        if not rows:
            raise RuntimeError(f"Minecraft bundler {field} is empty")
        return tuple(rows)

    @staticmethod
    def _write_verified_member(
        archive: ZipFile,
        source: str,
        destination: Path,
        expected_digest: str,
    ) -> None:
        try:
            payload = archive.read(source)
        except KeyError as exc:
            raise RuntimeError(
                "Minecraft bundler omitted declared runtime member: " + source
            ) from exc
        observed = hashlib.sha256(payload).hexdigest()
        if observed != expected_digest:
            raise RuntimeError(
                "Minecraft bundler runtime member digest mismatch: " + source
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(destination, payload)

    def _marker(self, key: str) -> Path:
        return self.metadata / f"{key}.json"

    def _resolved(self, key: str, *, asset_digest: str, version: str) -> MinecraftServerRuntimeDistribution | None:
        marker = self._marker(key)
        if not marker.is_file():
            return None
        try:
            stat = marker.stat()
            with self._verified_lock:
                if self._verified.get(key) == (int(stat.st_mtime_ns), int(stat.st_size)):
                    root = self.distributions / key
                    return MinecraftServerRuntimeDistribution(
                        key, root / "server.jar", root / "libraries"
                    )
            row = json.loads(marker.read_text(encoding="utf-8"))
            if row != {
                "schema": SERVER_RUNTIME_DISTRIBUTION_SCHEMA,
                "key": key,
                "asset_digest": asset_digest,
                "version": version,
            }:
                return None
            root = self.distributions / key
            distribution = MinecraftServerRuntimeDistribution(
                key, root / "server.jar", root / "libraries"
            )
            # Marker publication occurs only after every embedded member has
            # passed its Mojang SHA-256. Cache this exact marker generation so
            # hot acquisitions are O(1) stat/path checks rather than O(bytes).
            with self._verified_lock:
                self._verified[key] = (int(stat.st_mtime_ns), int(stat.st_size))
            return distribution
        except (OSError, ValueError, TypeError, json.JSONDecodeError, FileNotFoundError):
            return None

    def materialize(
        self,
        bundle_jar: str | Path,
        *,
        asset_digest: str,
        version: str,
    ) -> MinecraftServerRuntimeDistribution:
        require_sha256(asset_digest, "Minecraft server runtime asset_digest")
        if type(version) is not str or not version.strip() or version != version.strip():
            raise ValueError("Minecraft server runtime version must be canonical text")
        bundle = Path(bundle_jar).resolve()
        if not bundle.is_file():
            raise FileNotFoundError(bundle)
        key = canonical_digest(
            {
                "schema": SERVER_RUNTIME_DISTRIBUTION_SCHEMA,
                "asset_digest": asset_digest,
                "version": version,
            }
        )
        current = self._resolved(key, asset_digest=asset_digest, version=version)
        if current is not None:
            return current

        with InterprocessFileLock(self.locks / f"{key}.lock", blocking=True):
            current = self._resolved(key, asset_digest=asset_digest, version=version)
            if current is not None:
                return current

            target = self.distributions / key
            temporary = self.distributions / (
                f".{key}.tmp.{os.getpid()}.{threading.get_ident()}"
            )
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=False)
            temporary.mkdir(parents=True)
            try:
                with ZipFile(bundle) as archive:
                    versions = self._rows(
                        archive.read("META-INF/versions.list"),
                        field="versions.list",
                    )
                    libraries = self._rows(
                        archive.read("META-INF/libraries.list"),
                        field="libraries.list",
                    )
                    selected = tuple(row for row in versions if row[1] == version)
                    if len(selected) != 1:
                        raise RuntimeError(
                            "Minecraft bundler does not contain exactly one requested version"
                        )
                    version_digest, _identity, version_relative = selected[0]
                    self._write_verified_member(
                        archive,
                        "META-INF/versions/" + version_relative,
                        temporary / "server.jar",
                        version_digest,
                    )
                    for digest, _identity, relative in libraries:
                        self._write_verified_member(
                            archive,
                            "META-INF/libraries/" + relative,
                            temporary / "libraries" / relative,
                            digest,
                        )
                if target.exists():
                    shutil.rmtree(target, ignore_errors=False)
                durable_replace_directory(temporary, target)
                atomic_replace_bytes(
                    self._marker(key),
                    canonical_bytes(
                        {
                            "schema": SERVER_RUNTIME_DISTRIBUTION_SCHEMA,
                            "key": key,
                            "asset_digest": asset_digest,
                            "version": version,
                        }
                    ),
                )
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=False)

            resolved = self._resolved(key, asset_digest=asset_digest, version=version)
            if resolved is None:
                raise RuntimeError(
                    "Minecraft server runtime distribution failed atomic publication"
                )
            return resolved


__all__ = [
    "MinecraftServerRuntimeDistribution",
    "MinecraftServerRuntimeDistributionCache",
    "SERVER_RUNTIME_DISTRIBUTION_SCHEMA",
]
