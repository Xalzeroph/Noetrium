from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from noetrium_platform.composition.operator.wiring.research import main as research_main
from scripts.build_environment_images import (
    PYTHON_RUNTIME_CANONICAL_IMAGE,
    build_environment_images,
)
from scripts.resolve_project_environment_profiles import (
    resolve_project_environment_profiles,
)


def ensure_project_environment_closure(
    project_root: Path,
    *,
    work_root: Path,
) -> dict | None:
    project_root = Path(project_root).resolve()
    work_root = Path(work_root).resolve()
    profiles = resolve_project_environment_profiles(project_root)
    if not profiles:
        return None
    return build_environment_images(
        profiles=profiles,
        work_root=work_root,
        output=work_root / "environment-image-build.json",
        python_runtime_image=os.environ.get(
            "PYTHON_RUNTIME_IMAGE",
            PYTHON_RUNTIME_CANONICAL_IMAGE,
        ),
        python_runtime_canonical_image=os.environ.get(
            "PYTHON_RUNTIME_CANONICAL_IMAGE",
            PYTHON_RUNTIME_CANONICAL_IMAGE,
        ),
        profile_build_input_overrides={},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one project Research OS command after closing its "
            "environment realization requirements in the same control process."
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args, research_argv = parser.parse_known_args(
        sys.argv[1:] if argv is None else argv
    )
    if research_argv and research_argv[0] == "--":
        research_argv = research_argv[1:]
    if not research_argv or research_argv[0] != "run":
        raise ValueError("project control closure only accepts the run lifecycle")

    ensure_project_environment_closure(
        args.project_root,
        work_root=args.work_root,
    )
    return research_main(research_argv)


if __name__ == "__main__":
    raise SystemExit(main())
