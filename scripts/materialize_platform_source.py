from __future__ import annotations

import argparse
import json
from pathlib import Path

from noetrium_platform.composition.operator.project.platform_source_snapshot import (
    materialize_platform_source_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize one immutable content-addressed Noetrium platform source snapshot."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--snapshot-store", type=Path, required=True)
    args = parser.parse_args(argv)
    row = materialize_platform_source_snapshot(args.source_root, args.snapshot_store)
    print(json.dumps({
        "schema": "noetrium.platform-source-snapshot.v1",
        "root": str(row.root),
        "source_tree_sha256": row.source_tree_sha256,
        "manifest_digest": row.manifest_digest,
        "file_count": row.file_count,
        "total_bytes": row.total_bytes,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
