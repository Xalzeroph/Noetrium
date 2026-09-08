from __future__ import annotations

import json
from pathlib import Path

from check_readme_i18n import validate_root
from generate_downstream_contracts import generate
from readme_i18n import load_languages, mark_current, sync_navigation

ROOT = Path(__file__).resolve().parents[1]


def _required_current_locales(root: Path) -> tuple[str, ...]:
    manifest = load_languages(root)
    default = str(manifest["default"])
    return tuple(
        str(row["locale"])
        for row in manifest["languages"]
        if str(row["locale"]) == default or int(row.get("tier", 2)) <= 1
    )


def main() -> int:
    """Update generated public docs without hiding unrelated translation drift.

    The preflight is intentional: this command is for registry/API-generated
    changes only. If a human edited README semantics and translations are stale,
    the operator must reconcile those translations before this updater may stamp
    the generated-only Tier-1 surface current.
    """

    before = validate_root(ROOT)
    if before:
        print("GENERATED_DOCS_UPDATE_REFUSED")
        for error in before:
            print(f"- {error}")
        return 1

    status = generate(ROOT, check=False)
    if status != 0:
        return status

    navigation_changed = sync_navigation(ROOT)
    current_locales = _required_current_locales(ROOT)
    freshness_changed = mark_current(current_locales, ROOT)

    after = validate_root(ROOT)
    if after:
        print("GENERATED_DOCS_UPDATE_INVALID")
        for error in after:
            print(f"- {error}")
        return 1

    print(
        json.dumps(
            {
                "schema": "noetrium-generated-docs-update.v1",
                "current_locales": current_locales,
                "navigation_changed": navigation_changed,
                "freshness_changed": freshness_changed,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
