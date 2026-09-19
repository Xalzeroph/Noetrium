from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib
from typing import Any

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .authority import (
    MINEDOJO_AUDITED_COMMIT,
    MINEDOJO_BENCHMARK_TASK_COUNT,
    MINEDOJO_CREATIVE_TASK_COUNT,
    MINEDOJO_PLAYTHROUGH_TASK_COUNT,
    MINEDOJO_PROGRAMMATIC_FAMILIES,
    MINEDOJO_PROGRAMMATIC_TASK_COUNT,
)
from .cut import MineDojoTaskRecord, bind_minedojo_cut
from .source_manifest import minedojo_task_source_manifest_digest


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in sorted(
                value.items(),
                key=lambda row: str(row[0]),
            )
        }
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return tuple(_plain(item) for item in value)
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise TypeError(
        "MineDojo official task registry contains unsupported "
        f"value type: {type(value).__qualname__}"
    )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _task_ids(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows = tuple(value)
    if any(type(row) is not str or not row.strip() for row in rows):
        raise TypeError(f"{field_name} must contain task ids")
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must contain unique task ids")
    return rows


def _programmatic_family(spec: Mapping[str, Any]) -> str:
    raw = spec.get("__cls__")
    if type(raw) is not str:
        raise ValueError(
            "MineDojo programmatic task spec requires __cls__"
        )
    normalized = raw.strip().lower().replace("-", "_")
    aliases = {
        "techtree": "tech_tree",
        "tech_tree": "tech_tree",
        "harvest": "harvest",
        "combat": "combat",
        "survival": "survival",
    }
    try:
        family = aliases[normalized]
    except KeyError as exc:
        raise ValueError(
            f"unsupported MineDojo programmatic family: {raw}"
        ) from exc
    if family not in MINEDOJO_PROGRAMMATIC_FAMILIES:
        raise ValueError("MineDojo programmatic family drifted")
    return family


def materialize_official_minedojo_records(
    registry: object,
    *,
    installed_source_commit: str,
) -> tuple[MineDojoTaskRecord, ...]:
    """Project the audited official task registry into immutable task records.

    The adapter intentionally relies on the official MineDojo loader to parse
    and expand OmegaConf/YAML. No YAML parser or MineDojo project structure is
    embedded into Noetrium platform code.
    """

    if installed_source_commit != MINEDOJO_AUDITED_COMMIT:
        raise ValueError(
            "installed MineDojo source commit does not match audited "
            "paper-consistent commit"
        )

    programmatic_ids = _task_ids(
        getattr(registry, "ALL_PROGRAMMATIC_TASK_IDS"),
        "MineDojo ALL_PROGRAMMATIC_TASK_IDS",
    )
    creative_ids = _task_ids(
        getattr(registry, "ALL_CREATIVE_TASK_IDS"),
        "MineDojo ALL_CREATIVE_TASK_IDS",
    )
    playthrough_id = getattr(registry, "PLAYTHROUGH_TASK_ID")
    if type(playthrough_id) is not str or not playthrough_id.strip():
        raise ValueError("MineDojo PLAYTHROUGH_TASK_ID is required")

    p_instructions = _mapping(
        getattr(registry, "P_TASKS_PROMPTS_GUIDANCE"),
        "MineDojo P_TASKS_PROMPTS_GUIDANCE",
    )
    c_instructions = _mapping(
        getattr(registry, "C_TASKS_PROMPTS_GUIDANCE"),
        "MineDojo C_TASKS_PROMPTS_GUIDANCE",
    )
    playthrough = _mapping(
        getattr(registry, "PLAYTHROUGH_PROMPT_GUIDANCE"),
        "MineDojo PLAYTHROUGH_PROMPT_GUIDANCE",
    )
    specs = _mapping(
        getattr(registry, "ALL_TASKS_SPECS"),
        "MineDojo ALL_TASKS_SPECS",
    )

    if len(programmatic_ids) != MINEDOJO_PROGRAMMATIC_TASK_COUNT:
        raise ValueError("MineDojo programmatic task count drifted")
    if len(creative_ids) != MINEDOJO_CREATIVE_TASK_COUNT:
        raise ValueError("MineDojo creative task count drifted")
    if playthrough_id not in playthrough:
        raise ValueError("MineDojo playthrough registry drifted")
    if playthrough_id not in specs:
        raise ValueError("MineDojo playthrough task spec is missing")

    source_digest = minedojo_task_source_manifest_digest()
    records: list[MineDojoTaskRecord] = []

    for task_id in programmatic_ids:
        if task_id not in p_instructions or task_id not in specs:
            raise ValueError(
                f"MineDojo programmatic task is incomplete: {task_id}"
            )
        instruction = _mapping(
            p_instructions[task_id],
            f"MineDojo instruction {task_id}",
        )
        spec = _mapping(
            specs[task_id],
            f"MineDojo task spec {task_id}",
        )
        prompt = instruction.get("prompt")
        guidance = instruction.get("guidance")
        if type(prompt) is not str or not prompt.strip():
            raise ValueError(f"MineDojo task {task_id} has no prompt")
        if type(guidance) is not str or not guidance.strip():
            raise ValueError(f"MineDojo task {task_id} has no guidance")
        family = _programmatic_family(spec)
        records.append(
            MineDojoTaskRecord(
                task_id=task_id,
                category="programmatic",
                family=family,
                prompt=prompt,
                guidance_digest=canonical_digest(guidance),
                content_digest=canonical_digest({
                    "source_manifest_digest": source_digest,
                    "task_id": task_id,
                    "category": "programmatic",
                    "family": family,
                    "instruction": _plain(instruction),
                    "environment_spec": _plain(spec),
                }),
            )
        )

    for task_id in creative_ids:
        if task_id not in c_instructions:
            raise ValueError(
                f"MineDojo creative task is incomplete: {task_id}"
            )
        instruction = _mapping(
            c_instructions[task_id],
            f"MineDojo creative instruction {task_id}",
        )
        prompt = instruction.get("prompt")
        guidance = instruction.get("guidance")
        if type(prompt) is not str or not prompt.strip():
            raise ValueError(f"MineDojo task {task_id} has no prompt")
        if type(guidance) is not str or not guidance.strip():
            raise ValueError(f"MineDojo task {task_id} has no guidance")
        records.append(
            MineDojoTaskRecord(
                task_id=task_id,
                category="creative",
                family="creative",
                prompt=prompt,
                guidance_digest=canonical_digest(guidance),
                content_digest=canonical_digest({
                    "source_manifest_digest": source_digest,
                    "task_id": task_id,
                    "category": "creative",
                    "instruction": _plain(instruction),
                }),
            )
        )

    playthrough_instruction = _mapping(
        playthrough[playthrough_id],
        "MineDojo playthrough instruction",
    )
    prompt = playthrough_instruction.get("prompt")
    guidance = playthrough_instruction.get("guidance")
    if type(prompt) is not str or not prompt.strip():
        raise ValueError("MineDojo playthrough has no prompt")
    if type(guidance) is not str or not guidance.strip():
        raise ValueError("MineDojo playthrough has no guidance")
    records.append(
        MineDojoTaskRecord(
            task_id=playthrough_id,
            category="playthrough",
            family="playthrough",
            prompt=prompt,
            guidance_digest=canonical_digest(guidance),
            content_digest=canonical_digest({
                "source_manifest_digest": source_digest,
                "task_id": playthrough_id,
                "category": "playthrough",
                "instruction": _plain(playthrough_instruction),
                "environment_spec": _plain(specs[playthrough_id]),
            }),
        )
    )

    if len(records) != MINEDOJO_BENCHMARK_TASK_COUNT:
        raise ValueError("MineDojo total task count drifted")
    ids = tuple(row.task_id for row in records)
    if len(ids) != len(set(ids)):
        raise ValueError("MineDojo materialized task ids are not unique")
    return tuple(records)


def bind_official_minedojo_registry(
    registry: object,
    *,
    installed_source_commit: str,
):
    records = materialize_official_minedojo_records(
        registry,
        installed_source_commit=installed_source_commit,
    )
    return bind_minedojo_cut(
        records,
        source_digest=minedojo_task_source_manifest_digest(),
    )


def load_official_minedojo_records(
    *,
    installed_source_commit: str,
) -> tuple[MineDojoTaskRecord, ...]:
    registry = importlib.import_module("minedojo.tasks")
    return materialize_official_minedojo_records(
        registry,
        installed_source_commit=installed_source_commit,
    )


__all__ = [
    "bind_official_minedojo_registry",
    "load_official_minedojo_records",
    "materialize_official_minedojo_records",
]
