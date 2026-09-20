from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "deploy" / "environments" / "catalog.json"


def _load() -> dict:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if data.get("schema") != "noetrium.environment-container-profiles.v1":
        raise RuntimeError("environment profile catalog schema is not current")
    return data


def _profiles(data: dict) -> dict[str, dict]:
    rows = data.get("profiles")
    if not isinstance(rows, list):
        raise RuntimeError("environment profile catalog profiles must be a list")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("environment profile catalog entries must be objects")
        profile_id = row.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise RuntimeError("environment profile id must be non-empty")
        if profile_id in result:
            raise RuntimeError(f"duplicate environment profile: {profile_id}")
        result[profile_id] = row
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("profile_id")
    args = parser.parse_args(argv)

    data = _load()
    profiles = _profiles(data)
    if args.command == "list":
        for profile_id in sorted(profiles):
            row = profiles[profile_id]
            print(json.dumps({
                "profile_id": profile_id,
                "category_id": row["category_id"],
                "build_mode": row.get("build_mode", "environment-image"),
                "compose": row.get("compose"),
            }, sort_keys=True))
        return 0

    try:
        row = profiles[args.profile_id]
    except KeyError:
        print(f"unknown environment profile: {args.profile_id}", file=sys.stderr)
        return 2
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
