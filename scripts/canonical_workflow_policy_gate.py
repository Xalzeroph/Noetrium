#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER_NAME = 'git config user.name "Xalzeroph"'
OWNER_EMAIL = 'git config user.email "203086430+Xalzeroph@users.noreply.github.com"'
WORKFLOWS = (
    ROOT / ".github/workflows/canonical_projection_sync.yml",
    ROOT / ".github/workflows/research_projection_sync.yml",
)


def validate() -> tuple[str, ...]:
    errors: list[str] = []
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        if "--force" in text:
            errors.append(f"{rel}: force push is forbidden")
        if "github-actions[bot]" in text:
            errors.append(f"{rel}: projection commits must not use bot contributor identity")
        if OWNER_NAME not in text or OWNER_EMAIL not in text:
            errors.append(f"{rel}: canonical Xalzeroph contributor identity is missing")
        if "git push origin HEAD:main" not in text:
            errors.append(f"{rel}: projection publication must use ordinary fast-forward push to main")
        if "codex/**" in text:
            errors.append(f"{rel}: development branch projection trigger is forbidden")

    canonical = WORKFLOWS[0].read_text(encoding="utf-8")
    research = WORKFLOWS[1].read_text(encoding="utf-8")
    if "branches: [main]" not in canonical:
        errors.append("canonical projection workflow must trigger only on main")
    if "branches: [main]" not in research:
        errors.append("research projection workflow must trigger only on main")
    return tuple(errors)


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("canonical workflow policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
