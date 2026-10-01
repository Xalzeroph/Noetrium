from __future__ import annotations

import argparse
import json
from pathlib import Path

from noetrium_platform.composition.environment_profile_selection import (
    default_profiles_for_categories,
    required_environment_categories,
)
from noetrium_platform.composition.operator.project.project_research_os_loader import (
    load_project_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "deploy" / "environments" / "catalog.json"


def resolve_project_environment_profiles(
    project_root: Path,
    *,
    catalog_path: Path = DEFAULT_CATALOG,
) -> tuple[str, ...]:
    portfolio = load_project_portfolio(project_root)
    categories = required_environment_categories(portfolio)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if type(catalog) is not dict:
        raise ValueError("environment profile catalog must be a JSON object")
    return default_profiles_for_categories(catalog, categories)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    profiles = resolve_project_environment_profiles(
        args.project,
        catalog_path=args.catalog,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{profile}\n" for profile in profiles), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
