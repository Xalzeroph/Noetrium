from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable


AuthorityMatcher = Callable[[ast.Call, dict[str, str]], bool]


@dataclass(frozen=True, slots=True)
class SourceAuthorityViolation:
    authority: str
    primitive: str
    module: str
    path: str
    line: int
    allowed_modules: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class SourceAuthorityRule:
    authority: str
    primitive: str
    allowed_modules: tuple[str, ...]
    matches: AuthorityMatcher


__all__ = ["AuthorityMatcher", "SourceAuthorityRule", "SourceAuthorityViolation"]
