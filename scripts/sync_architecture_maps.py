#!/usr/bin/env python3
"""Project and verify source-derived architecture maps as coherent structural cuts.

Architecture maps are generated projections, not authorities. A projection-only
commit naturally has a different Git HEAD from the source commit that last changed
its structure. Projection is therefore idempotent across projection-only commits:
if regenerated structure is byte-identical after normalizing provenance, the
stored source-cut SHA is preserved and no new projection commit is produced.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_code_architecture_map as core_map
import generate_repository_code_architecture_map as repository_map

_SOURCE_SHA_LINE = re.compile(r"(?m)^> Source Git SHA: `[^`]+`\.$")
Builder = Callable[[], tuple[dict[str, object], str]]


def _index_text(index: dict[str, object]) -> str:
    return json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _with_source_sha(
    index: dict[str, object],
    markdown: str,
    source_sha: str,
) -> tuple[dict[str, object], str]:
    normalized = dict(index)
    normalized["source_git_sha"] = source_sha
    replaced, count = _SOURCE_SHA_LINE.subn(
        f"> Source Git SHA: `{source_sha}`.",
        markdown,
        count=1,
    )
    if count != 1:
        raise RuntimeError("architecture map is missing exactly one source Git SHA header")
    return normalized, replaced


def _read_stored(
    *,
    index_path: Path,
    map_path: Path,
) -> tuple[dict[str, object], str, str] | None:
    if not index_path.is_file() or not map_path.is_file():
        return None
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(index, dict):
        return None
    source_sha = index.get("source_git_sha")
    if type(source_sha) is not str or not source_sha:
        return None
    try:
        markdown = map_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return index, markdown, source_sha


def _matches_stored_structure(
    *,
    generated_index: dict[str, object],
    generated_markdown: str,
    index_path: Path,
    map_path: Path,
) -> tuple[bool, str | None]:
    stored = _read_stored(index_path=index_path, map_path=map_path)
    if stored is None:
        return False, None
    stored_index, stored_markdown, stored_sha = stored
    normalized_index, normalized_markdown = _with_source_sha(
        generated_index,
        generated_markdown,
        stored_sha,
    )
    return (
        _index_text(stored_index) == _index_text(normalized_index)
        and stored_markdown == normalized_markdown,
        stored_sha,
    )


def _write_projection(
    *,
    index: dict[str, object],
    markdown: str,
    index_path: Path,
    map_path: Path,
) -> str:
    source_sha = index.get("source_git_sha")
    if type(source_sha) is not str or not source_sha:
        raise RuntimeError("generated architecture index has no source_git_sha")
    index_path.write_text(_index_text(index), encoding="utf-8")
    map_path.write_text(markdown, encoding="utf-8")
    return source_sha


def project() -> int:
    core_index, core_markdown = core_map.build()
    repository_index, repository_markdown = repository_map.build()

    core_generated_sha = core_index.get("source_git_sha")
    repository_generated_sha = repository_index.get("source_git_sha")
    if (
        type(core_generated_sha) is not str
        or type(repository_generated_sha) is not str
        or core_generated_sha != repository_generated_sha
    ):
        raise RuntimeError(
            "architecture generators did not observe one source cut: "
            f"core={core_generated_sha} repository={repository_generated_sha}"
        )

    core_current, core_stored_sha = _matches_stored_structure(
        generated_index=core_index,
        generated_markdown=core_markdown,
        index_path=core_map.INDEX_PATH,
        map_path=core_map.MAP_PATH,
    )
    repository_current, repository_stored_sha = _matches_stored_structure(
        generated_index=repository_index,
        generated_markdown=repository_markdown,
        index_path=repository_map.INDEX_PATH,
        map_path=repository_map.MAP_PATH,
    )

    if (
        core_current
        and repository_current
        and core_stored_sha is not None
        and core_stored_sha == repository_stored_sha
    ):
        print(
            "ARCHITECTURE_MAP_PROJECT_PASS "
            f"source_git_sha={core_stored_sha} changed=false"
        )
        return 0

    core_sha = _write_projection(
        index=core_index,
        markdown=core_markdown,
        index_path=core_map.INDEX_PATH,
        map_path=core_map.MAP_PATH,
    )
    repository_sha = _write_projection(
        index=repository_index,
        markdown=repository_markdown,
        index_path=repository_map.INDEX_PATH,
        map_path=repository_map.MAP_PATH,
    )
    if core_sha != repository_sha:
        raise RuntimeError(
            "architecture projections were generated from different source cuts: "
            f"core={core_sha} repository={repository_sha}"
        )
    print(
        "ARCHITECTURE_MAP_PROJECT_PASS "
        f"source_git_sha={core_sha} changed=true"
    )
    return 0


def _check_projection(
    *,
    label: str,
    builder: Builder,
    index_path: Path,
    map_path: Path,
) -> tuple[bool, str | None]:
    stored = _read_stored(index_path=index_path, map_path=map_path)
    if stored is None:
        print(f"{label}: architecture projection is missing or invalid")
        return False, None
    stored_index, stored_markdown, stored_sha = stored

    generated_index, generated_markdown = builder()
    generated_index, generated_markdown = _with_source_sha(
        generated_index,
        generated_markdown,
        stored_sha,
    )

    ok = True
    if _index_text(stored_index) != _index_text(generated_index):
        print(f"{label}: architecture index is stale")
        ok = False
    if stored_markdown != generated_markdown:
        print(f"{label}: architecture map is stale")
        ok = False
    return ok, stored_sha


def verify_build() -> int:
    """Verify that both architecture generators close coherently on exact source.

    This is the non-materializing CI gate. Checked-in projection freshness is
    owned by canonical-projection-sync; platform assurance must not race that
    materializer on the source commit that triggered it.
    """
    core_index, core_markdown = core_map.build()
    repository_index, repository_markdown = repository_map.build()

    core_sha = core_index.get("source_git_sha")
    repository_sha = repository_index.get("source_git_sha")
    if type(core_sha) is not str or type(repository_sha) is not str or core_sha != repository_sha:
        print(
            "architecture generators observed different source cuts: "
            f"core={core_sha} repository={repository_sha}"
        )
        return 1

    for label, index, markdown in (
        ("core", core_index, core_markdown),
        ("repository", repository_index, repository_markdown),
    ):
        counts = index.get("counts")
        if not isinstance(counts, dict):
            print(f"{label}: generated architecture index has no counts")
            return 1
        if counts.get("parse_errors") != 0:
            print(f"{label}: generated architecture index contains parse errors")
            return 1
        try:
            _index_text(index).encode("utf-8")
            _with_source_sha(index, markdown, core_sha)
        except (TypeError, ValueError, RuntimeError) as exc:
            print(f"{label}: generated architecture projection is invalid: {exc}")
            return 1

    print(f"ARCHITECTURE_MAP_BUILD_PASS source_git_sha={core_sha}")
    return 0


def check() -> int:
    core_ok, core_sha = _check_projection(
        label="core",
        builder=core_map.build,
        index_path=core_map.INDEX_PATH,
        map_path=core_map.MAP_PATH,
    )
    repository_ok, repository_sha = _check_projection(
        label="repository",
        builder=repository_map.build,
        index_path=repository_map.INDEX_PATH,
        map_path=repository_map.MAP_PATH,
    )
    if core_sha is not None and repository_sha is not None and core_sha != repository_sha:
        print(
            "architecture projections describe different source cuts: "
            f"core={core_sha} repository={repository_sha}"
        )
        return 1
    if not (core_ok and repository_ok):
        return 1
    print(f"ARCHITECTURE_MAP_CHECK_PASS source_git_sha={core_sha}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project or verify canonical source-derived architecture maps."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--verify-build", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if args.verify_build:
        return verify_build()
    return project()


if __name__ == "__main__":
    raise SystemExit(main())
