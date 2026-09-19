from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from noetrium_platform.foundation.governance.repository_boundary.cli import main

if __name__ == "__main__":
    raise SystemExit(main([str(ROOT), *sys.argv[1:]]))
