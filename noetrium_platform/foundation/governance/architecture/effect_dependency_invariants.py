from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_tree

from .source_scan import SourceInvariantViolation, imports, violation


def audit_effect_dependency_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    journal = root / "noetrium_platform" / "infrastructure" / "reliability" / "effect" / "runtime"
    if journal.exists():
        forbidden_prefixes = (
            "noetrium_platform.capabilities.participant.agent.api", "noetrium_platform.capabilities.participant.capability.api",
            "noetrium_platform.capabilities.environment.runtime.api", "noetrium_platform.capabilities.participant.method.api",
            "noetrium_platform.research.experimentation.study", "noetrium_platform.research.execution.workflow.implementations",
            "projects",
        )
        for path in sorted(journal.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith(forbidden_prefixes):
                    rows.append(violation(root, path, "effect_journal_domain_firewall", line, f"generic effect journal imports higher/concrete runtime domain {module}"))

    for base in (root / "noetrium_platform" / "research" / "experimentation" / "experiment", root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations", root / "projects"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith("noetrium_platform.infrastructure.reliability.effect.runtime"):
                    rows.append(violation(root, path, "effect_contract_dependency_direction", line, f"domain/scientific logic imports effect journal implementation {module}; depend on noetrium_platform.infrastructure.reliability.effect.api"))

    legacy = journal / "invariants.py"
    if legacy.exists():
        rows.append(violation(root, legacy, "effect_transition_authority", 1, "effect journal reintroduced domain transition invariants; keep them in effect_api.transitions"))
    for name in ("memory.py", "persistent.py"):
        path = journal / name
        if not path.exists():
            continue
        tree = source_tree(path)
        imported_transition_names = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "noetrium_platform.infrastructure.reliability.effect.api"
            for alias in node.names
            if alias.name in {"prepare_transition", "effect_transition", "consumed_transition", "not_applied_transition"}
        }
        required = {"prepare_transition", "effect_transition", "consumed_transition", "not_applied_transition"}
        missing = sorted(required - imported_transition_names)
        if missing:
            rows.append(violation(root, path, "effect_transition_authority", 1, f"effect journal adapter bypasses shared transition authority: missing imports {missing}"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "EffectIntentRecord":
                rows.append(violation(root, path, "effect_transition_authority", node.lineno, "effect journal adapter constructs EffectIntentRecord directly; use effect_api transition functions"))
    return rows


__all__ = ["audit_effect_dependency_invariants"]
