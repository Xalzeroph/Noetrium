#!/usr/bin/env python3
"""Project or verify the machine-readable core-platform architecture index."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_code_architecture_map as core_map


def _text(index: dict[str, object]) -> str:
    return json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _valid(index: dict[str, object]) -> bool:
    counts = index.get("counts")
    return isinstance(counts, dict) and counts.get("parse_errors") == 0 and isinstance(index.get("source_tree_sha256"), str)


def _read() -> dict[str, object] | None:
    try:
        value = json.loads(core_map.INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def project() -> int:
    index = core_map.build()[0]
    if not _valid(index):
        raise RuntimeError("generated platform architecture index is invalid")
    stored = _read()
    if stored is not None and _text(index) == _text(stored):
        print(f"PLATFORM_ARCHITECTURE_PROJECT_PASS source_tree_sha256={index['source_tree_sha256']} changed=false")
        return 0
    core_map.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    core_map.INDEX_PATH.write_text(_text(index), encoding="utf-8")
    print(f"PLATFORM_ARCHITECTURE_PROJECT_PASS source_tree_sha256={index['source_tree_sha256']} changed=true")
    return 0


def check() -> int:
    stored = _read()
    index = core_map.build()[0]
    if stored is None or not _valid(index) or not _valid(stored):
        print("platform: architecture index is missing or invalid")
        return 1
    if _text(index) != _text(stored):
        print("platform: architecture index is stale")
        return 1
    print(f"PLATFORM_ARCHITECTURE_CHECK_PASS source_tree_sha256={stored['source_tree_sha256']}")
    return 0


def verify_build() -> int:
    index = core_map.build()[0]
    if not _valid(index):
        print("platform: generated architecture index is invalid")
        return 1
    print(f"PLATFORM_ARCHITECTURE_BUILD_PASS source_tree_sha256={index['source_tree_sha256']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project or verify the Noetrium platform architecture index.")
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
