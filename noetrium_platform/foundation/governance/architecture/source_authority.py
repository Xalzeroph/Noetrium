from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .source_authority_contracts import SourceAuthorityRule, SourceAuthorityViolation
from .source_authority_engine import audit_authority_rules
from .source_authority_rules import DEFAULT_SOURCE_AUTHORITY_RULES
from .extensions import discover_architecture_extensions


def architecture_source_authority_rules(root: Path) -> tuple[SourceAuthorityRule, ...]:
    resolved = Path(root).resolve()
    rules = list(DEFAULT_SOURCE_AUTHORITY_RULES)
    for extension in discover_architecture_extensions(resolved):
        rules.extend(getattr(extension, "SOURCE_AUTHORITY_RULES", ()))
    return tuple(rules)


def audit_source_authorities(
    root: Path,
    rules: Iterable[SourceAuthorityRule] | None = None,
) -> tuple[SourceAuthorityViolation, ...]:
    """Audit production call-sites against core + repository extension authority rules."""
    resolved = Path(root).resolve()
    return audit_authority_rules(
        resolved,
        architecture_source_authority_rules(resolved) if rules is None else rules,
    )


__all__ = [
    "DEFAULT_SOURCE_AUTHORITY_RULES",
    "SourceAuthorityRule",
    "SourceAuthorityViolation",
    "architecture_source_authority_rules",
    "audit_source_authorities",
]
