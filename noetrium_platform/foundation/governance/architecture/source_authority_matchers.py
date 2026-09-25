from __future__ import annotations

import ast

from .source_authority_contracts import AuthorityMatcher


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def resolved_symbol_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    dotted = dotted_name(node)
    if not dotted:
        return None
    first, *rest = dotted.split(".")
    resolved = aliases.get(first, first)
    return ".".join([resolved, *rest]) if rest else resolved


def resolved_call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    return resolved_symbol_name(call.func, aliases)


def exact_call(*names: str) -> AuthorityMatcher:
    wanted = frozenset(names)
    return lambda call, aliases: resolved_call_name(call, aliases) in wanted


def path_open_write_mode() -> AuthorityMatcher:
    """Match pathlib-style .open() calls whose explicit mode can mutate bytes."""

    def matches(call: ast.Call, aliases: dict[str, str]) -> bool:
        del aliases
        dotted = dotted_name(call.func) or ""
        if not dotted.endswith(".open"):
            return False
        mode_node: ast.AST | None = call.args[0] if call.args else None
        for keyword in call.keywords:
            if keyword.arg == "mode":
                mode_node = keyword.value
                break
        if not isinstance(mode_node, ast.Constant) or not isinstance(
            mode_node.value, str
        ):
            return False
        return any(flag in mode_node.value for flag in ("w", "a", "x", "+"))

    return matches


def suffix_call(*suffixes: str) -> AuthorityMatcher:
    wanted = tuple(suffixes)

    def matches(call: ast.Call, aliases: dict[str, str]) -> bool:
        del aliases
        dotted = dotted_name(call.func) or ""
        return any(dotted == suffix or dotted.endswith(f".{suffix}") for suffix in wanted)

    return matches


__all__ = [
    "dotted_name",
    "resolved_call_name",
    "resolved_symbol_name",
    "exact_call",
    "path_open_write_mode",
    "suffix_call",
]
