from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_bytes, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
    durable_unlink,
)

from ..api import MinecraftWorldCut
from .world_cut_integrity import local_path


class MinecraftBranchCheckpointError(RuntimeError):
    """An authoritative branch-world checkpoint could not be restored safely."""


class ContractDigestFactory(Protocol):
    def __call__(self) -> str: ...


class MinecraftBranchRestoreJournal:
    """Durable codec and identity authority for branch restore intent."""

    SCHEMA = "minecraft-branch-checkpoint-restore.v1"
    PHASES = frozenset({"prepared", "backup_published", "committed"})

    def __init__(
        self,
        *,
        path: Path,
        environment_generation: str,
        server_workdir: str,
        level_name: str,
        contract_digest: ContractDigestFactory,
    ) -> None:
        self.path = path
        self.environment_generation = environment_generation
        self.server_workdir = server_workdir
        self.level_name = level_name
        self.contract_digest = contract_digest

    def build(
        self,
        *,
        cut: MinecraftWorldCut,
        backup: Path,
        phase: str,
    ) -> dict[str, JsonValue]:
        if phase not in self.PHASES:
            raise ValueError(f"unsupported restore phase: {phase}")
        document: dict[str, JsonValue] = {
            "schema_version": self.SCHEMA,
            "environment_generation": self.environment_generation,
            "server_contract_digest": self.contract_digest(),
            "server_workdir": self.server_workdir,
            "level_name": self.level_name,
            "cut_id": cut.cut_id,
            "manifest_digest": cut.manifest_digest,
            "backup_path": str(backup),
            "phase": phase,
        }
        document["record_digest"] = canonical_digest(document)
        return document

    def publish(self, document: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        normalized = dict(document)
        payload = {
            key: value
            for key, value in normalized.items()
            if key != "record_digest"
        }
        normalized["record_digest"] = canonical_digest(payload)
        atomic_replace_bytes(self.path, canonical_bytes(normalized))
        return normalized

    def set_phase(
        self,
        document: Mapping[str, JsonValue],
        phase: str,
    ) -> dict[str, JsonValue]:
        updated = dict(document)
        updated["phase"] = phase
        return self.publish(updated)

    def clear(self) -> None:
        durable_unlink(self.path)

    def load(self) -> dict[str, JsonValue] | None:
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal is unreadable or corrupt"
            ) from exc
        expected = {
            "schema_version",
            "environment_generation",
            "server_contract_digest",
            "server_workdir",
            "level_name",
            "cut_id",
            "manifest_digest",
            "backup_path",
            "phase",
            "record_digest",
        }
        if not isinstance(document, Mapping) or set(document) != expected:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal schema is invalid"
            )
        self._validate_digest(document)
        self._validate_identity(document)
        self._validate_restore_target(document)
        return dict(document)

    @staticmethod
    def _validate_digest(document: Mapping[str, JsonValue]) -> None:
        record_digest = document.get("record_digest")
        if not isinstance(record_digest, str) or len(record_digest) != 64:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal digest is invalid"
            )
        payload = {
            key: value
            for key, value in document.items()
            if key != "record_digest"
        }
        if canonical_digest(payload) != record_digest.lower():
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal digest mismatch"
            )

    def _validate_identity(self, document: Mapping[str, JsonValue]) -> None:
        if document.get("schema_version") != self.SCHEMA:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal version mismatch"
            )
        if document.get("environment_generation") != self.environment_generation:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal generation mismatch"
            )
        if document.get("server_contract_digest") != self.contract_digest():
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal server mismatch"
            )
        if document.get("server_workdir") != self.server_workdir:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal workdir mismatch"
            )
        if document.get("level_name") != self.level_name:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal level mismatch"
            )
        phase = document.get("phase")
        if phase not in self.PHASES:
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal phase is invalid"
            )
        cut_id = document.get("cut_id")
        if not isinstance(cut_id, str) or not cut_id.strip():
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal cut identity is invalid"
            )
        manifest_digest = document.get("manifest_digest")
        if (
            not isinstance(manifest_digest, str)
            or len(manifest_digest) != 64
            or any(
                char not in "0123456789abcdef"
                for char in manifest_digest.lower()
            )
        ):
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal manifest digest is invalid"
            )

    def _validate_restore_target(
        self,
        document: Mapping[str, JsonValue],
    ) -> None:
        backup_raw = document.get("backup_path")
        if not isinstance(backup_raw, str) or not backup_raw.strip():
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal backup path is invalid"
            )
        workdir = local_path(self.server_workdir, field="server_workdir")
        backup = local_path(
            backup_raw,
            field="checkpoint_restore_backup",
        )
        expected_prefix = f".{workdir.name}.checkpoint-backup-"
        if (
            backup.parent != workdir.parent
            or not backup.name.startswith(expected_prefix)
        ):
            raise MinecraftBranchCheckpointError(
                "branch checkpoint restore journal backup path is invalid"
            )


__all__ = [
    "ContractDigestFactory",
    "MinecraftBranchCheckpointError",
    "MinecraftBranchRestoreJournal",
]
