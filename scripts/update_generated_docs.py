from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_downstream_contracts import generate
from readme_i18n import load_languages, mark_current, sync_navigation
from check_readme_i18n import validate_root


def update(root: Path) -> int:
    result = generate(root, check=False)
    if result != 0:
        return result
    sync_navigation(root)
    locales = tuple(row["locale"] for row in load_languages(root)["languages"])
    mark_current(locales, root)
    return 0


def check(root: Path) -> int:
    if generate(root, check=True) != 0:
        return 1
    errors = validate_root(root)
    if errors:
        print("generated documentation check failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("GENERATED_DOCUMENTATION_CHECK_PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate Noetrium public facades, catalogs, README blocks, and freshness state."
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    return check(root) if args.check else update(root)


if __name__ == "__main__":
    raise SystemExit(main())
