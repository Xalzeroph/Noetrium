#!/usr/bin/env python3
"""Project or verify machine-readable source architecture indexes.

Human-readable architecture is maintained in docs/architecture/SYSTEM_ARCHITECTURE.md
and RUNTIME_AND_DEPLOYMENT.md. Generated topology remains machine-readable so CI
can verify exact source structure without publishing giant generated manuals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_code_architecture_map as core_map
import generate_repository_code_architecture_map as repository_map


def _text(index: dict[str, object]) -> str:
    return json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _read(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _valid(index: dict[str, object]) -> bool:
    counts = index.get("counts")
    return isinstance(counts, dict) and counts.get("parse_errors") == 0 and isinstance(index.get("source_tree_sha256"), str)


def project() -> int:
    pairs = (
        (core_map.INDEX_PATH, core_map.build()[0]),
        (repository_map.INDEX_PATH, repository_map.build()[0]),
    )
    if not all(_valid(index) for _, index in pairs):
        raise RuntimeError("architecture generators did not produce valid source cuts")
    changed = False
    for path, index in pairs:
        stored = _read(path)
        if stored is not None and _text(index) == _text(stored):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_text(index), encoding="utf-8")
        changed = True
    identities = ",".join(str(index["source_tree_sha256"])[:12] for _, index in pairs)
    print(f"ARCHITECTURE_INDEX_PROJECT_PASS source_tree_sha256={identities} changed={str(changed).lower()}")
    return 0


def verify_build() -> int:
    core = core_map.build()[0]
    repo = repository_map.build()[0]
    if not (_valid(core) and _valid(repo)):
        print("architecture index build is invalid")
        return 1
    print(f"ARCHITECTURE_INDEX_BUILD_PASS core={str(core['source_tree_sha256'])[:12]} repository={str(repo['source_tree_sha256'])[:12]}")
    return 0


def check() -> int:
    ok = True
    for label, path, index in (
        ("core", core_map.INDEX_PATH, core_map.build()[0]),
        ("repository", repository_map.INDEX_PATH, repository_map.build()[0]),
    ):
        stored = _read(path)
        if stored is None or not _valid(stored):
            print(f"{label}: architecture index is missing or invalid")
            ok = False
            continue
        if _text(index) != _text(stored):
            print(f"{label}: architecture index is stale")
            ok = False
    if ok:
        print("ARCHITECTURE_INDEX_CHECK_PASS")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project or verify source-derived architecture indexes.")
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
