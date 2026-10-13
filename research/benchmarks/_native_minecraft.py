from __future__ import annotations

"""Strict loader for benchmark-owned Minecraft native-port snapshots.

This module is downstream research asset infrastructure, not platform runtime.
It converts audited, immutable benchmark-port facts into the generic Noetrium
Benchmark Unit ABI and rejects legacy command-level execution semantics.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_TASK_SETUP_SCHEMA_V2,
    MINECRAFT_TASK_SUCCESS_KINDS,
    normalize_minecraft_world_ops,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    TaskVerifierIsolation,
    benchmark_cut_unit,
    split_unit,
    task_package,
    task_unit,
)

COMMON_SUBSTRATE_ENVIRONMENT_REQUIREMENT = "environment.minecraft"
NATIVE_MINECRAFT_TASK_PACKAGE_SCHEMA = "noetrium.minecraft-native-benchmark-task-package.v1"


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    return tuple(value)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _contains_legacy_command_semantics(value: object) -> bool:
    if isinstance(value, Mapping):
        if any(key in value for key in ("verification_command", "scenario")):
            return True
        return any(_contains_legacy_command_semantics(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_legacy_command_semantics(item) for item in value)
    return False


def load_native_minecraft_snapshot(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    root = _mapping(payload, "native benchmark snapshot")
    _text(root.get("benchmark_id"), "native benchmark id")
    _text(root.get("revision_id"), "native benchmark revision")
    _text(root.get("task_schema_id"), "native benchmark task schema")
    require_sha256(str(root.get("source_digest", "")), "native benchmark source digest")
    if _contains_legacy_command_semantics(root):
        raise ValueError(
            "native Minecraft benchmark snapshot contains legacy scenario/verification_command semantics"
        )
    port = _mapping(root.get("native_port"), "native benchmark port metadata")
    if port.get("runtime") != MINECRAFT_TASK_SETUP_SCHEMA_V2:
        raise ValueError("native Minecraft benchmark port is not task-setup v2")
    tasks = _sequence(root.get("tasks"), "native benchmark tasks")
    if not tasks:
        raise ValueError("native benchmark must contain tasks")
    for raw in tasks:
        task = _mapping(raw, "native benchmark task")
        content = _mapping(task.get("content"), "native benchmark task content")
        setup = _mapping(content.get("environment_setup"), "native task environment_setup")
        minecraft = _mapping(setup.get("minecraft"), "native task Minecraft setup")
        if minecraft.get("schema") != MINECRAFT_TASK_SETUP_SCHEMA_V2:
            raise ValueError("native benchmark task must use Minecraft setup v2")
        normalize_minecraft_world_ops(minecraft.get("world_ops", ()))
        success = _mapping(content.get("success"), "native task success contract")
        success_kind = str(success.get("kind", ""))
        if success_kind == "source_only_unqualified":
            continue
        if success_kind not in MINECRAFT_TASK_SUCCESS_KINDS:
            raise ValueError(
                f"native benchmark task has unsupported success kind: {success.get('kind')!r}"
            )
    return root


def build_native_minecraft_cut(path: Path) -> NoetriumUnit:
    root = load_native_minecraft_snapshot(path)
    revision = str(root["revision_id"])
    task_schema = str(root["task_schema_id"])
    port_digest = canonical_digest(root["native_port"])
    tasks = []
    for raw in root["tasks"]:
        row = _mapping(raw, "native benchmark task")
        content = _mapping(row["content"], "native benchmark task content")
        objective = content.get("objective", content.get("goal"))
        if type(objective) is not str or not objective.strip():
            raise ValueError("native Minecraft task requires objective/goal")
        lineage = tuple(str(value) for value in row.get("lineage_refs", ()))
        success = _mapping(content.get("success"), "native benchmark task success")
        executable = str(success.get("kind", "")) != "source_only_unqualified"
        package = (
            task_package(
                NATIVE_MINECRAFT_TASK_PACKAGE_SCHEMA,
                canonical_digest({"objective": objective}),
                environment_requirement_id=COMMON_SUBSTRATE_ENVIRONMENT_REQUIREMENT,
                verifier_requirement_id=None,
                verifier_isolation=TaskVerifierIsolation.SEPARATE,
            )
            if executable
            else None
        )
        tasks.append(task_unit(
            str(row["task_id"]),
            revision_id=str(row.get("revision_id", revision)),
            family=str(row["family"]),
            schema_id=str(row.get("schema_id", task_schema)),
            content_digest=None,
            content=dict(content),
            lineage_refs=(*lineage, f"noetrium-native-port:{port_digest}"),
            package=package,
        ))
    by_id = {str(task.parameters["task_id"]): task for task in tasks}
    splits = []
    for raw in root.get("splits", ()):
        row = _mapping(raw, "native benchmark split")
        ids = tuple(str(value) for value in row["task_ids"])
        if any(task_id not in by_id for task_id in ids):
            raise ValueError("native benchmark split references unknown task")
        splits.append(split_unit(str(row["split_id"]), ids))
    selection_digest = canonical_digest({
        "schema": "noetrium.minecraft-native-benchmark-selection.v1",
        "source_digest": root["source_digest"],
        "native_port_digest": port_digest,
        "task_ids": tuple(str(row.parameters["task_id"]) for row in tasks),
        "splits": tuple(
            (str(row.unit_id), tuple(row.parameters["task_ids"])) for row in splits
        ),
    })
    return benchmark_cut_unit(
        str(root["benchmark_id"]),
        revision,
        str(root["source_digest"]),
        task_schema,
        tuple(tasks),
        splits=tuple(splits),
        selection_policy_digest=selection_digest,
    )


__all__ = [
    "COMMON_SUBSTRATE_ENVIRONMENT_REQUIREMENT",
    "NATIVE_MINECRAFT_TASK_PACKAGE_SCHEMA",
    "build_native_minecraft_cut",
    "load_native_minecraft_snapshot",
]
