from __future__ import annotations

from types import SimpleNamespace

import pytest

from research.benchmarks.minedojo import (
    MINEDOJO_TASK_DESCRIPTION_TREE_GIT_SHA,
    MINEDOJO_TASK_SOURCE_BLOBS,
    bind_official_minedojo_registry,
    materialize_official_minedojo_records,
    minedojo_task_source_manifest_digest,
)
from research.reproductions.minedojo.fidelity import (
    MINEDOJO_REFERENCE_FIDELITY,
)
from research.reproductions.minedojo.source import MINEDOJO_AUDITED_COMMIT


def _registry():
    programmatic_ids = []
    p_instructions = {}
    specs = {}
    families = ("Combat", "Harvest", "TechTree", "Survival")
    for index in range(
        MINEDOJO_REFERENCE_FIDELITY.programmatic_task_count
    ):
        raw_family = families[index % len(families)]
        task_id = f"{raw_family.lower()}_fixture_{index:04d}"
        programmatic_ids.append(task_id)
        p_instructions[task_id] = {
            "prompt": f"programmatic prompt {index}",
            "guidance": f"programmatic guidance {index}",
        }
        specs[task_id] = {
            "__cls__": raw_family,
            "target_quantities": 1,
            "fixture": index,
        }

    creative_ids = []
    c_instructions = {}
    for index in range(
        MINEDOJO_REFERENCE_FIDELITY.creative_task_count
    ):
        task_id = f"creative:{index}"
        creative_ids.append(task_id)
        c_instructions[task_id] = {
            "prompt": f"creative prompt {index}",
            "guidance": f"creative guidance {index}",
            "collection": "manual",
            "source": None,
        }

    specs["playthrough"] = {
        "__cls__": "Playthrough",
        "fixture": "playthrough",
    }
    return SimpleNamespace(
        ALL_PROGRAMMATIC_TASK_IDS=programmatic_ids,
        ALL_CREATIVE_TASK_IDS=creative_ids,
        PLAYTHROUGH_TASK_ID="playthrough",
        P_TASKS_PROMPTS_GUIDANCE=p_instructions,
        C_TASKS_PROMPTS_GUIDANCE=c_instructions,
        PLAYTHROUGH_PROMPT_GUIDANCE={
            "playthrough": {
                "prompt": "Defeat the Ender Dragon.",
                "guidance": "Find and defeat the dragon.",
            }
        },
        ALL_TASKS_SPECS=specs,
    )


def test_minedojo_source_manifest_freezes_official_task_authorities() -> None:
    assert MINEDOJO_TASK_DESCRIPTION_TREE_GIT_SHA == (
        "03b41574f3f7ca6129b260d250ee83f7f4bf54b8"
    )
    assert len(MINEDOJO_TASK_SOURCE_BLOBS) == 6
    by_path = {row.path: row for row in MINEDOJO_TASK_SOURCE_BLOBS}
    assert (
        by_path[
            "minedojo/tasks/description_files/programmatic_tasks.yaml"
        ].git_blob_sha
        == "a051d5f0e8a47696aa153501bf27fcdc74db94d6"
    )
    assert (
        by_path[
            "minedojo/tasks/description_files/creative_tasks.yaml"
        ].size_bytes
        == 521736
    )
    assert len(minedojo_task_source_manifest_digest()) == 64


def test_minedojo_official_registry_materializes_3142_content_addressed_tasks() -> None:
    registry = _registry()
    records = materialize_official_minedojo_records(
        registry,
        installed_source_commit=MINEDOJO_AUDITED_COMMIT,
    )
    assert len(records) == 3142
    assert sum(row.category == "programmatic" for row in records) == 1581
    assert sum(row.category == "creative" for row in records) == 1560
    assert sum(row.category == "playthrough" for row in records) == 1
    assert len({row.task_id for row in records}) == 3142
    assert all(len(row.content_digest) == 64 for row in records)
    assert all(
        row.guidance_digest is not None
        and len(row.guidance_digest) == 64
        for row in records
    )

    resolution = bind_official_minedojo_registry(
        registry,
        installed_source_commit=MINEDOJO_AUDITED_COMMIT,
    )
    assert len(resolution.task_set.tasks) == 3142
    assert (
        resolution.source.content_digest
        == minedojo_task_source_manifest_digest()
    )


def test_minedojo_materializer_rejects_unverified_source_commit() -> None:
    with pytest.raises(
        ValueError,
        match="does not match audited",
    ):
        materialize_official_minedojo_records(
            _registry(),
            installed_source_commit="0" * 40,
        )
