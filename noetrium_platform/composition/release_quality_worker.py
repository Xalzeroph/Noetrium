from __future__ import annotations

"""Isolated worker entry point for release-quality read-only lanes."""

import argparse
import json
from pathlib import Path

from .release_quality import _architecture_lane, _static_quality_lane


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lane", choices=("architecture", "static"))
    parser.add_argument("root")
    args = parser.parse_args(argv)
    root = str(Path(args.root).resolve())
    if args.lane == "architecture":
        digest, clean = _architecture_lane(root)
        payload = {"architecture_report_sha256": digest, "architecture_clean": clean}
    else:
        payload = _static_quality_lane(root)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
