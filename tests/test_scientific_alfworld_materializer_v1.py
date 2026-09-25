from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.benchmarks.alfworld import (
    ALFWORLD_PAPER_EVAL_SPLIT,
    ALFWORLD_RELEASE_COMMIT,
    ALFWORLD_RELEASE_VERSION,
    materialize_alfworld_paper_eval,
    register_alfworld_materialization,
)

_RAW_FAMILIES = (
    "pick_and_place_simple",
    "pick_clean_then_place_in_recep",
    "pick_heat_then_place_in_recep",
    "pick_cool_then_place_in_recep",
    "look_at_obj_in_light",
    "pick_two_obj_and_place",
)


class _Provider:
    def __init__(self, game_files: tuple[str, ...]) -> None:
        self.game_files = list(game_files)


def _dataset(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    root = tmp_path / "alfworld-data"
    eval_root = root / "json_2.1.1" / "valid_unseen"
    logic = root / "logic"
    logic.mkdir(parents=True)
    (logic / "alfred.pddl").write_text("(define (domain alfred))", encoding="utf-8")
    (logic / "alfred.twl2").write_text("grammar", encoding="utf-8")

    game_files: list[str] = []
    for index in range(134):
        raw_family = _RAW_FAMILIES[index % len(_RAW_FAMILIES)]
        task = eval_root / raw_family / f"scene-{index:03d}"
        task.mkdir(parents=True)
        (task / "traj_data.json").write_text(
            json.dumps({"task_type": raw_family, "task_index": index}, sort_keys=True),
            encoding="utf-8",
        )
        (task / "initial_state.pddl").write_text(f"initial-{index}", encoding="utf-8")
        (task / "game.tw-pddl").write_text(
            json.dumps({"solvable": True, "task_index": index}, sort_keys=True),
            encoding="utf-8",
        )
        game_files.append(str(task / "game.tw-pddl"))
    return root, tuple(game_files)


def _materialize(root: Path, order: tuple[str, ...]):
    return materialize_alfworld_paper_eval(
        _Provider(order),
        data_root=root,
        installed_source_commit=ALFWORLD_RELEASE_COMMIT,
        installed_version=ALFWORLD_RELEASE_VERSION,
    )


def test_materializer_freezes_official_provider_order_without_resorting(tmp_path: Path) -> None:
    root, paths = _dataset(tmp_path)
    provider_order = paths[67:] + paths[:67]
    materialized = _materialize(root, provider_order)

    expected = tuple(
        "alfworld:" + Path(path).resolve().relative_to(
            (root / "json_2.1.1" / "valid_unseen").resolve()
        ).as_posix()
        for path in provider_order
    )
    assert tuple(row.task_id for row in materialized.records) == expected
    selected = materialized.resolution.task_set.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)
    assert tuple(row.task_id for row in selected) == expected
    assert len(materialized.records) == 134
    assert len({row.family for row in materialized.records}) == 6


def test_task_content_identity_is_independent_of_provider_ordinal(tmp_path: Path) -> None:
    root, paths = _dataset(tmp_path)
    first = _materialize(root, paths)
    second = _materialize(root, paths[1:] + paths[:1])

    by_id_first = {row.task_id: row.content_digest for row in first.records}
    by_id_second = {row.task_id: row.content_digest for row in second.records}
    assert by_id_first == by_id_second
    assert first.provider_order_digest != second.provider_order_digest
    assert first.source_digest != second.source_digest


def test_materializer_rejects_source_authority_drift(tmp_path: Path) -> None:
    root, paths = _dataset(tmp_path)
    with pytest.raises(ValueError, match="source commit"):
        materialize_alfworld_paper_eval(
            _Provider(paths),
            data_root=root,
            installed_source_commit="0" * 40,
            installed_version=ALFWORLD_RELEASE_VERSION,
        )


def test_materializer_rejects_provider_gamefile_outside_eval_cut(tmp_path: Path) -> None:
    root, paths = _dataset(tmp_path)
    outside = root / "json_2.1.1" / "valid_seen" / "escape" / "game.tw-pddl"
    outside.parent.mkdir(parents=True)
    outside.write_text("{}", encoding="utf-8")
    order = (str(outside), *paths[1:])
    with pytest.raises(ValueError, match="escapes frozen ALFWorld dataset root"):
        _materialize(root, order)


def test_text_runtime_authority_freezes_historical_dependency_commits() -> None:
    from research.benchmarks.alfworld import (
        ALFWORLD_FAST_DOWNWARD_COMMIT,
        ALFWORLD_TEXTWORLD_COMMIT,
        ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST,
    )

    assert ALFWORLD_TEXTWORLD_COMMIT == "634f9f91fec732a79dd9e7623675301a53f06623"
    assert ALFWORLD_FAST_DOWNWARD_COMMIT == "84769171b9d965bf5739eaa7cf6604b0d9697534"
    assert len(ALFWORLD_TEXT_RUNTIME_AUTHORITY_DIGEST) == 64


def test_materialization_registers_exact_benchmark_authority(tmp_path: Path) -> None:
    root, paths = _dataset(tmp_path)
    materialized = _materialize(root, paths)
    registration = register_alfworld_materialization(materialized)

    assert registration.resolution == materialized.resolution
    assert registration.benchmark_id == materialized.resolution.task_set.benchmark_id
    assert len(registration.authority_proof_digest) == 64
    assert len(registration.registration_digest) == 64
