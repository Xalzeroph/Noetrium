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


def resolved_call_name(call: ast.Call, aliases: dict[str, str]) -> str | None:
    dotted = dotted_name(call.func)
    if not dotted:
        return None
    first, *rest = dotted.split(".")
    resolved = aliases.get(first, first)
    return ".".join([resolved, *rest]) if rest else resolved


def exact_call(*names: str) -> AuthorityMatcher:
    wanted = frozenset(names)
    return lambda call, aliases: resolved_call_name(call, aliases) in wanted


def suffix_call(*suffixes: str) -> AuthorityMatcher:
    wanted = tuple(suffixes)

    def matches(call: ast.Call, aliases: dict[str, str]) -> bool:
        del aliases
        dotted = dotted_name(call.func) or ""
        return any(dotted == suffix or dotted.endswith(f".{suffix}") for suffix in wanted)

    return matches


__all__ = ["dotted_name", "resolved_call_name", "exact_call", "suffix_call"]
