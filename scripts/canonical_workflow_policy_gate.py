#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / ".github/workflows/canonical_projection_sync.yml"
RESEARCH = (
    ROOT / ".github/workflows/research_projection_sync.yml",
    ROOT / ".github/workflows/research_workspace.yml",
)


def _read_only_errors(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    errors: list[str] = []
    for token in ("contents: write", "git push", "git commit", "git add", "git reset --hard"):
        if token in text:
            errors.append(f"{rel}: workflow must be read-only; found {token!r}")
    if "contents: read" not in text:
        errors.append(f"{rel}: workflow requires read-only contents permission")
    if "codex/**" in text:
        errors.append(f"{rel}: development branch trigger is forbidden")
    return errors


def validate() -> tuple[str, ...]:
    errors = _read_only_errors(CANONICAL)
    canonical = CANONICAL.read_text(encoding="utf-8")
    if "push:" not in canonical or "branches: [main]" not in canonical:
        errors.append("canonical projection workflow must verify main pushes")
    if "--check" not in canonical:
        errors.append("canonical projection workflow must use generator check mode")

    for path in RESEARCH:
        errors.extend(_read_only_errors(path))
        text = path.read_text(encoding="utf-8")
        if "workflow_dispatch:" not in text:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: research maintenance must be explicitly dispatched")
        if "push:" in text or "pull_request:" in text:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: research workspace must not gate main/release CI")
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
