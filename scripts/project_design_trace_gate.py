#!/usr/bin/env python3
"""Reject project-design source identities from production implementation.

External project identities belong only to research/audit/reproduction material.
Production code must contain native Noetrium semantics, not source-project names,
compatibility facades, or project-shaped bridges.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LIST = ROOT / "docs/research/external_audits/project_design_sources.txt"
PROTECTED_ROOTS = (
    ROOT / "noetrium_platform",
    ROOT / "noetrium",
    ROOT / "components",
    ROOT / "orchestration",
    ROOT / "examples",
)
TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml",
    ".md", ".txt",
}


def _tokens() -> tuple[str, ...]:
    rows: list[str] = []
    for raw in SOURCE_LIST.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        rows.append(value)
    if not rows:
        raise RuntimeError("external project design source list is empty")
    return tuple(dict.fromkeys(rows))


def _pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    left = r"(?<![A-Za-z0-9])" if token[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if token[-1].isalnum() else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


def main() -> int:
    patterns = tuple((token, _pattern(token)) for token in _tokens())
    violations: list[str] = []
    for root in PROTECTED_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                for token, pattern in patterns:
                    if pattern.search(line):
                        rel = path.relative_to(ROOT).as_posix()
                        violations.append(f"{rel}:{line_number}: external project identity {token!r}")
    if violations:
        print("PROJECT_DESIGN_TRACE_GATE_FAIL")
        for row in violations:
            print(row)
        return 1
    print("PROJECT_DESIGN_TRACE_GATE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
