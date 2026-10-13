from __future__ import annotations

import ast
from pathlib import Path

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort


from .api.contracts import SilentFailureFinding


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}


def _handler_is_silent(handler: ast.ExceptHandler) -> bool:
    body = handler.body
    if not body:
        return True
    return all(
        isinstance(stmt, (ast.Pass, ast.Continue))
        or (isinstance(stmt, ast.Return) and stmt.value is None)
        for stmt in body
    )


def _is_suppress_broad(node: ast.Call) -> bool:
    fn = node.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "suppress"):
        return False
    return any(
        isinstance(arg, ast.Name) and arg.id in {"Exception", "BaseException"}
        for arg in node.args
    )


def _scan_tree(path: str, tree: ast.AST) -> tuple[SilentFailureFinding, ...]:
    findings: list[SilentFailureFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad(node) and _handler_is_silent(node):
            findings.append(SilentFailureFinding(
                path, node.lineno, "silent_broad_except", "broad exception is discarded without evidence"
            ))
        elif isinstance(node, ast.Call) and _is_suppress_broad(node):
            findings.append(SilentFailureFinding(
                path, node.lineno, "broad_suppress", "contextlib.suppress discards Exception/BaseException"
            ))
    return tuple(findings)


def scan_silent_failures(
    root: Path,
    *,
    source_index: RepositorySourceIndexPort | None = None,
    path_prefixes: tuple[str, ...] = (),
) -> tuple[SilentFailureFinding, ...]:
    findings: list[SilentFailureFinding] = []
    if source_index is not None:
        for source in source_index.documents(suffixes={".py"}):
            if path_prefixes and not any(
                source.relative_path == prefix.rstrip("/")
                or source.relative_path.startswith(prefix.rstrip("/") + "/")
                for prefix in path_prefixes
            ):
                continue
            if "except" not in source.text and "suppress" not in source.text:
                continue
            tree = source_index.python_tree(source.relative_path, sha256=source.sha256)
            findings.extend(_scan_tree(source.relative_path, tree))
        return tuple(findings)

    root = Path(root)
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            findings.append(SilentFailureFinding(str(path), 0, "parse_error", str(exc)))
            continue
        if "except" not in text and "suppress" not in text:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            findings.append(SilentFailureFinding(
                str(path), getattr(exc, "lineno", 0) or 0, "parse_error", str(exc)
            ))
            continue
        findings.extend(_scan_tree(str(path), tree))
    return tuple(findings)


__all__ = ["SilentFailureFinding", "scan_silent_failures"]
