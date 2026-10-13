from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading

from noetrium_platform.foundation.kernel.kernel.durability import durable_replace_directory

from noetrium_platform.foundation.kernel.kernel import (
    InterprocessFileLock,
    atomic_replace_bytes,
    canonical_bytes,
    canonical_digest,
    sha256_file,
)

BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA = "noetrium.minecraft-bridge-runtime-distribution.v2"
_PACKAGE_ROOT_FILES = ("package.json", "package-lock.json")
_ENTRYPOINT = "bridge.js"
_LOCAL_REQUIRE_PATTERN = re.compile(
    r"require\(\s*(['\"])\./([^'\"]+)\1\s*\)"
)


@dataclass(frozen=True, slots=True)
class MinecraftBridgeRuntimeDistribution:
    key: str
    root: Path

    @property
    def entrypoint(self) -> Path:
        path = self.root / _ENTRYPOINT
        if not path.is_file():
            raise FileNotFoundError(path)
        return path


class MinecraftBridgeRuntimeDistributionCache:
    """Immutable content-addressed Mineflayer bridge source snapshots."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.distributions = self.root / "distributions"
        self.metadata = self.root / "metadata"
        self.locks = self.root / "locks"
        for path in (self.distributions, self.metadata, self.locks):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _local_runtime_files(source_root: str | Path) -> tuple[str, ...]:
        """Return the exact transitive CommonJS runtime source closure.

        Package metadata and the bridge entrypoint are the only explicit roots.
        Every local JavaScript dependency is discovered from relative require
        edges, so adding a runtime module cannot silently produce an incomplete
        content-addressed distribution.
        """

        root = Path(source_root).resolve()
        pending = [_ENTRYPOINT]
        discovered: set[str] = set()

        while pending:
            relative = pending.pop()
            if relative in discovered:
                continue
            path = root / relative
            if not path.is_file():
                raise FileNotFoundError(path)
            discovered.add(relative)
            if path.suffix != ".js":
                continue
            source = path.read_text(encoding="utf-8")
            parent = PurePosixPath(relative).parent
            for match in _LOCAL_REQUIRE_PATTERN.finditer(source):
                dependency = PurePosixPath(match.group(2))
                if dependency.suffix == "":
                    dependency = dependency.with_suffix(".js")
                resolved = parent / dependency
                if resolved.is_absolute() or ".." in resolved.parts:
                    raise ValueError(
                        "Minecraft bridge local dependency escapes source root: "
                        + str(resolved)
                    )
                pending.append(resolved.as_posix())

        return tuple(sorted((*_PACKAGE_ROOT_FILES, *discovered)))

    @classmethod
    def source_manifest(
        cls,
        source_root: str | Path,
    ) -> tuple[tuple[str, str], ...]:
        root = Path(source_root).resolve()
        rows = []
        for relative in cls._local_runtime_files(root):
            path = root / relative
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append((relative, sha256_file(path)))
        return tuple(rows)

    def materialize(
        self,
        source_root: str | Path,
    ) -> MinecraftBridgeRuntimeDistribution:
        source = Path(source_root).resolve()
        manifest = self.source_manifest(source)
        key = canonical_digest({
            "schema": BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA,
            "files": manifest,
        })
        target = self.distributions / key
        marker = self.metadata / f"{key}.json"
        expected = {
            "schema": BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA,
            "key": key,
            "files": manifest,
        }

        def resolved() -> MinecraftBridgeRuntimeDistribution | None:
            if not marker.is_file() or not target.is_dir():
                return None
            try:
                if marker.read_bytes() != canonical_bytes(expected):
                    return None
                for relative, digest in manifest:
                    path = target / relative
                    if not path.is_file() or sha256_file(path) != digest:
                        return None
                return MinecraftBridgeRuntimeDistribution(key, target)
            except OSError:
                return None

        current = resolved()
        if current is not None:
            return current
        with InterprocessFileLock(self.locks / f"{key}.lock", blocking=True):
            current = resolved()
            if current is not None:
                return current
            temporary = self.distributions / (
                f".{key}.tmp.{os.getpid()}.{threading.get_ident()}"
            )
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(parents=True)
            try:
                for relative, digest in manifest:
                    source_path = source / relative
                    payload = source_path.read_bytes()
                    destination = temporary / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    atomic_replace_bytes(destination, payload)
                    if sha256_file(destination) != digest:
                        raise RuntimeError(
                            "Minecraft bridge runtime copy digest mismatch: "
                            + relative
                        )
                if target.exists():
                    shutil.rmtree(target)
                durable_replace_directory(temporary, target)
                atomic_replace_bytes(marker, canonical_bytes(expected))
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            current = resolved()
            if current is None:
                raise RuntimeError(
                    "Minecraft bridge runtime distribution failed publication"
                )
            return current


__all__ = [
    "BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA",
    "MinecraftBridgeRuntimeDistribution",
    "MinecraftBridgeRuntimeDistributionCache",
]
