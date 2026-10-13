"""Generate the derived Noetrium capability index."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.architecture.capability_index import (
    write_capability_index,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/architecture/CAPABILITY_INDEX.json")
    args = parser.parse_args()
    value = write_capability_index(ROOT, ROOT / args.output)
    print(value["index_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
