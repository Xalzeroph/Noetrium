from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_text, source_tree

from .source_scan import SourceInvariantViolation, is_transient_source_path, violation


def _exception_type_names(node: ast.expr | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Tuple):
        names: set[str] = set()
        for item in node.elts:
            names.update(_exception_type_names(item))
        return names
    return set()


def _handler_raw_renderings(handler: ast.ExceptHandler) -> tuple[tuple[int, str], ...]:
    if not isinstance(handler.name, str):
        return ()
    name = handler.name
    rows: set[tuple[int, str]] = set()
    for node in ast.walk(handler):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == name
        ):
            rows.add((node.lineno, f"{node.func.id}({name})"))
        elif (
            isinstance(node, ast.FormattedValue)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
        ):
            rows.add((node.lineno, f"formatted exception {{{name}}}"))
    return tuple(sorted(rows))


def audit_document_integrity_invariants(root: Path) -> list[SourceInvariantViolation]:
    """Protect machine-classified document integrity from free-text re-encoding."""

    package = root / "noetrium_platform"
    rows: list[SourceInvariantViolation] = []
    if not package.exists():
        return rows
    for path in sorted(package.rglob("*.py")):
        if path.name == "checksummed_document.py" or is_transient_source_path(path):
            continue
        if "ChecksummedDocumentError" not in source_text(path):
            continue
        tree = source_tree(path)
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            if "ChecksummedDocumentError" not in _exception_type_names(handler.type):
                continue
            for line, rendering in _handler_raw_renderings(handler):
                rows.append(
                    violation(
                        root,
                        path,
                        "document_integrity_machine_semantics",
                        line,
                        (
                            "checksummed-document failure is re-encoded as free text "
                            f"({rendering}); preserve its machine code/cause and use a stable domain message"
                        ),
                    )
                )
    return rows


__all__ = ["audit_document_integrity_invariants"]
