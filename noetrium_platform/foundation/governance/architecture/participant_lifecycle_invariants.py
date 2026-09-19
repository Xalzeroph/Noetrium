from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, violation


def _python_files(base: Path) -> tuple[Path, ...]:
    return tuple(sorted(base.rglob("*.py"))) if base.exists() else ()


def audit_participant_lifecycle_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    definition = root / "noetrium_platform" / "capabilities" / "participant" / "definition" / "runtime"
    binding = root / "noetrium_platform" / "capabilities" / "participant" / "binding" / "runtime"
    resolver = binding / "local_resolver.py"
    for path in (definition / "catalog.py", binding / "configuration.py", resolver):
        if not path.exists():
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "open_session":
                rows.append(violation(root, path, "participant_session_lifecycle_authority", node.lineno, "implementation/configuration/resolver authority must not own open_session lifecycle"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open_session":
                rows.append(violation(root, path, "participant_session_lifecycle_authority", node.lineno, "implementation/configuration/resolver authority must not invoke open_session lifecycle"))

    owner = root / "noetrium_platform" / "research" / "execution" / "participants" / "session_lifecycle.py"
    if owner.exists():
        owner_tree = source_tree(owner)
        owners = {
            "resolve": root / "noetrium_platform" / "research" / "execution" / "participants" / "resolution.py",
            "open_session": owner,
            "close": owner,
            "checkpoint": root / "noetrium_platform" / "research" / "execution" / "participants" / "checkpoint_operations.py",
            "restore": root / "noetrium_platform" / "research" / "execution" / "participants" / "checkpoint_operations.py",
        }
        for verb, verb_owner in owners.items():
            if not verb_owner.exists():
                rows.append(violation(root, verb_owner, "participant_runtime_lifecycle_backbone", 1, f"generic participant runtime operation owner missing for verb={verb}"))
                continue
            verb_tree = owner_tree if verb_owner == owner else source_tree(verb_owner)
            found = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "participant_operation_type"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == verb
                for node in ast.walk(verb_tree)
            )
            if not found:
                rows.append(violation(root, verb_owner, "participant_runtime_lifecycle_backbone", 1, f"generic participant runtime lifecycle missing operation verb={verb}"))

    forbidden_names = {"ResearchMethodEndpoint", "AgentRuntimeEndpoint", "EnvironmentRuntimeEndpoint", "CapabilityProviderRuntimeEndpoint"}
    domain_roots = (
        root / "noetrium_platform" / "capabilities" / "participant" / "method" / "api",
        root / "noetrium_platform" / "capabilities" / "participant" / "agent" / "api",
        root / "noetrium_platform" / "capabilities" / "environment" / "runtime" / "api",
        root / "noetrium_platform" / "capabilities" / "participant" / "capability" / "api",
    )
    for base in domain_roots:
        for path in _python_files(base):
            tree = source_tree(path)
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name in forbidden_names:
                    rows.append(violation(root, path, "participant_runtime_endpoint_single_authority", node.lineno, f"domain API reintroduced runtime endpoint lifecycle protocol {node.name}; use participant_api.ParticipantRuntimeEndpoint"))
    return rows


__all__ = ["audit_participant_lifecycle_invariants"]
