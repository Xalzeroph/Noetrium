#!/usr/bin/env python3
"""Project and verify the canonical Noetrium platform architecture map.

This script intentionally has no repository-workspace or reproduction knowledge.
It derives architecture only from noetrium_platform via
generate_code_architecture_map.py. Repository/reproduction maps are separate
workspace artifacts and are not part of platform assurance or release authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_code_architecture_map as core_map

_SOURCE_SHA_LINE = re.compile(r"(?m)^> Source Git SHA: [^\n]+$")


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
        f"> Source Git SHA: " + chr(96) + source_sha + chr(96) + ".",
        markdown,
        count=1,
    )
    if count != 1:
        raise RuntimeError("platform architecture map is missing exactly one source Git SHA header")
    return normalized, replaced


def _read_stored() -> tuple[dict[str, object], str, str] | None:
    if not core_map.INDEX_PATH.is_file() or not core_map.MAP_PATH.is_file():
        return None
    try:
        index = json.loads(core_map.INDEX_PATH.read_text(encoding="utf-8"))
        markdown = core_map.MAP_PATH.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(index, dict):
        return None
    source_sha = index.get("source_git_sha")
    if type(source_sha) is not str or not source_sha:
        return None
    return index, markdown, source_sha


def _generated_is_valid(index: dict[str, object], markdown: str) -> None:
    counts = index.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("platform architecture index has no counts")
    if counts.get("parse_errors") != 0:
        raise RuntimeError("platform architecture index contains parse errors")
    source_sha = index.get("source_git_sha")
    if type(source_sha) is not str or not source_sha:
        raise RuntimeError("platform architecture index has no source_git_sha")
    _index_text(index).encode("utf-8")
    _with_source_sha(index, markdown, source_sha)


def project() -> int:
    generated_index, generated_markdown = core_map.build()
    _generated_is_valid(generated_index, generated_markdown)
    stored = _read_stored()
    if stored is not None:
        stored_index, stored_markdown, stored_sha = stored
        normalized_index, normalized_markdown = _with_source_sha(
            generated_index,
            generated_markdown,
            stored_sha,
        )
        if (
            _index_text(stored_index) == _index_text(normalized_index)
            and stored_markdown == normalized_markdown
        ):
            print(
                "PLATFORM_ARCHITECTURE_PROJECT_PASS "
                f"source_git_sha={stored_sha} changed=false"
            )
            return 0

    core_map.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    core_map.INDEX_PATH.write_text(_index_text(generated_index), encoding="utf-8")
    core_map.MAP_PATH.write_text(generated_markdown, encoding="utf-8")
    print(
        "PLATFORM_ARCHITECTURE_PROJECT_PASS "
        f"source_git_sha={generated_index['source_git_sha']} changed=true"
    )
    return 0


def check() -> int:
    stored = _read_stored()
    if stored is None:
        print("platform: architecture projection is missing or invalid")
        return 1
    stored_index, stored_markdown, stored_sha = stored
    generated_index, generated_markdown = core_map.build()
    try:
        _generated_is_valid(generated_index, generated_markdown)
        normalized_index, normalized_markdown = _with_source_sha(
            generated_index,
            generated_markdown,
            stored_sha,
        )
    except RuntimeError as exc:
        print(f"platform: generated architecture projection is invalid: {exc}")
        return 1
    if _index_text(stored_index) != _index_text(normalized_index):
        print("platform: architecture index is stale")
        return 1
    if stored_markdown != normalized_markdown:
        print("platform: architecture map is stale")
        return 1
    print(f"PLATFORM_ARCHITECTURE_CHECK_PASS source_git_sha={stored_sha}")
    return 0


def verify_build() -> int:
    index, markdown = core_map.build()
    try:
        _generated_is_valid(index, markdown)
    except RuntimeError as exc:
        print(f"platform: generated architecture projection is invalid: {exc}")
        return 1
    print(f"PLATFORM_ARCHITECTURE_BUILD_PASS source_git_sha={index['source_git_sha']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project or verify the canonical Noetrium platform architecture map."
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
