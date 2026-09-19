from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from noetrium_platform.foundation.governance.api import (
    RepositorySourceFailure,
    RepositorySourceFailureKind,
    RepositorySourceIncompleteError,
    RepositorySourceIndexPort,
)

from .degradation_contracts import BANNED_RUNTIME_IDENTIFIERS, DegradationFinding
from .degradation_paths import is_excluded_path, iter_audited_files

_BANNED_IDENTIFIER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(item) for item in sorted(BANNED_RUNTIME_IDENTIFIERS)) + r")\b"
)


def _findings(rel: Path, tree: ast.AST) -> Iterable[DegradationFinding]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.arg)):
            name = node.id if isinstance(node, ast.Name) else node.arg
            if name in BANNED_RUNTIME_IDENTIFIERS:
                yield DegradationFinding(rel.as_posix(), node.lineno, name, "python_identifier")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_RUNTIME_IDENTIFIERS:
            yield DegradationFinding(rel.as_posix(), node.lineno, node.attr, "python_attribute")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in BANNED_RUNTIME_IDENTIFIERS
        ):
            yield DegradationFinding(rel.as_posix(), node.lineno, node.value, "python_literal_key")


def scan_python_degradation(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort | None = None,
) -> Iterable[DegradationFinding]:
    if source_index is not None:
        for source in source_index.documents(suffixes={".py"}):
            rel = Path(source.relative_path)
            if is_excluded_path(rel) or _BANNED_IDENTIFIER_RE.search(source.text) is None:
                continue
            tree = source_index.python_tree(source.relative_path, sha256=source.sha256)
            yield from _findings(rel, tree)
        return

    for path in iter_audited_files(root, suffixes=frozenset({".py"})):
        rel = path.relative_to(root)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.FILE_READ,
                rel.as_posix(),
                type(exc).__name__,
            ),)) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.UTF8_DECODE,
                rel.as_posix(),
                "invalid utf-8",
            ),)) from exc
        try:
            tree = ast.parse(text, filename=rel.as_posix())
        except SyntaxError as exc:
            raise RepositorySourceIncompleteError((RepositorySourceFailure(
                RepositorySourceFailureKind.PYTHON_PARSE,
                rel.as_posix(),
                f"line {exc.lineno or 0}",
            ),)) from exc
        if _BANNED_IDENTIFIER_RE.search(text) is None:
            continue
        yield from _findings(rel, tree)


__all__ = ["scan_python_degradation"]
