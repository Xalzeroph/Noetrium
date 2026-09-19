"""Static containment rules for provider-native implementation imports."""
from __future__ import annotations

import ast

from noetrium_platform.foundation.governance.api import RepositorySourcePort
from noetrium_platform.foundation.governance.architecture.api.provider_ingress import (
    ProviderIngressBoundary,
    ProviderIngressContractError,
    ProviderIngressViolation,
)


def _module_for_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if not normalized.endswith(".py"):
        return ""
    stem = normalized[:-3]
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


def _imports(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.extend((getattr(node, "lineno", 0), alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            rows.append((getattr(node, "lineno", 0), node.module))
    return tuple(rows)


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def audit_provider_ingress_boundaries(
    source: RepositorySourcePort,
    boundaries: tuple[ProviderIngressBoundary, ...],
) -> tuple[ProviderIngressViolation, ...]:
    """Reject provider-native imports outside declared adapter packages.

    Algorithm-Complexity: O(S + I*P + V log V)
    Algorithm-Rationale: S is total selected Python source/AST size, I is the number
    of imports, P is the total declared implementation-prefix count, and V is the
    emitted violation count. Each source/import/prefix comparison is visited once;
    only the final deterministic violation ordering contributes V log V.

    Providers supply public declarations; Governance owns the rule. No MCP/SDK/CLI
    object model becomes a Platform contract merely because an adapter uses it.
    """
    if not isinstance(boundaries, tuple) or any(
        not isinstance(item, ProviderIngressBoundary) for item in boundaries
    ):
        raise ProviderIngressContractError("provider ingress boundaries must be a typed immutable tuple")
    identities = tuple(item.provider_identity for item in boundaries)
    if len(identities) != len(set(identities)):
        raise ProviderIngressContractError("provider ingress boundary identity must be unique")
    rows: list[ProviderIngressViolation] = []
    for blob in source.documents(suffixes=(".py",)):
        importer = _module_for_path(blob.relative_path)
        try:
            tree = ast.parse(blob.text, filename=blob.relative_path)
        except (SyntaxError, ValueError) as exc:
            rows.append(ProviderIngressViolation(
                "source_parse_failed", blob.relative_path, getattr(exc, "lineno", 0) or 0,
                "", None, "provider ingress audit requires parseable Python source",
            ))
            continue
        for line, imported in _imports(tree):
            matched = tuple(
                boundary
                for boundary in boundaries
                if any(_matches(imported, prefix) for prefix in boundary.implementation_import_prefixes)
            )
            if not matched:
                continue
            if any(_matches(importer, boundary.adapter_module_prefix) for boundary in matched):
                continue
            for boundary in matched:
                rows.append(ProviderIngressViolation(
                    "provider_native_import_escaped_adapter", blob.relative_path, line, imported,
                    boundary.provider_identity,
                    "provider-native implementation imports are confined to the declared adapter boundary",
                ))
    return tuple(sorted(set(rows)))


__all__ = ["audit_provider_ingress_boundaries"]
