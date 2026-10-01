from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_text, source_tree

from .source_scan import SourceInvariantViolation, imports, violation


_REQUIRED_EFFECT_INTENT_OPERATIONS = (
    "effect.intent.prepare",
    "effect.intent.result_record",
    "effect.intent.reconciled",
    "effect.intent.consumed",
    "effect.intent.not_applied",
)

_REQUIRED_WORKFLOW_OPERATIONS = {
    "agent_turn": (
        "agent.run_turn",
        "capability.invoke",
        "capability.effect.prepare",
        "capability.effect.reconcile",
    ),
}

_DISPATCH_AUTHORITIES = frozenset({
    "noetrium_platform/research/execution/workflow/runtime/operation_dispatch.py",
    "noetrium_platform/research/execution/participants/resolution.py",
    "noetrium_platform/research/execution/participants/checkpoint_operations.py",
    "noetrium_platform/research/execution/participants/session_lifecycle.py",
    "noetrium_platform/research/execution/workflow/runtime/effect_intents.py",
    "noetrium_platform/composition/workflows/agent_turn/capability_effect_provider.py",
    "noetrium_platform/composition/workflows/agent_turn/agent_turn_operations.py",
    "noetrium_platform/composition/workflows/agent_turn/capability_operations.py",
})


def _literal_operation_types(paths: tuple[Path, ...]) -> frozenset[str]:
    operations: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "operation_type"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    operations.add(keyword.value.value)
    return frozenset(operations)


def _audit_required_operations(
    root: Path,
    *,
    label: str,
    paths: tuple[Path, ...],
    required: tuple[str, ...],
) -> list[SourceInvariantViolation]:
    actual = _literal_operation_types(paths)
    base = str(paths[0].parent.relative_to(root)) if paths else label
    return [
        violation(root, base, f"{label}_operation_backbone", 1, f"missing required operation boundary: {op}")
        for op in required
        if op not in actual
    ]


def _audit_dispatch_authority(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    scan_roots = (
        root / "noetrium_platform" / "research" / "experimentation" / "experiment",
        root / "noetrium_platform" / "research" / "execution" / "workflow" / "runtime",
        root / "noetrium_platform" / "composition" / "workflows" / "agent_turn",
    )
    for base in scan_roots:
        if not base.exists():
            continue
        for path in sorted(base.glob("*.py")):
            tree = source_tree(path)
            rel = path.relative_to(root).as_posix()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "dispatch"
                    and rel not in _DISPATCH_AUTHORITIES
                ):
                    rows.append(violation(
                        root,
                        path,
                        "workflow_dispatch_authority",
                        node.lineno,
                        "direct operation dispatch is restricted to narrow operation adapters",
                    ))
    return rows



def _audit_workflow_dependency_direction(root: Path) -> list[SourceInvariantViolation]:
    """Scientific workflows depend on contracts only, never orchestration/runtime implementations."""

    workflows = root / "noetrium_platform" / "composition" / "workflows"
    if not workflows.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    forbidden = (
        "noetrium_platform.research.experimentation",
        "noetrium_platform.infrastructure.reliability.effect.runtime",
    )
    for path in sorted(workflows.rglob("*.py")):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "workflow_contract_dependency_direction",
                    line,
                    f"scientific workflow imports orchestration/runtime implementation {module}; depend on workflow_api/effect_api/participant_api contracts",
                ))
    return rows



def _audit_execution_core_composition_direction(root: Path) -> list[SourceInvariantViolation]:
    """Execution core is inner architecture and may never depend on composition roots."""

    base = root / "noetrium_platform" / "research" / "execution"
    if not base.exists():
        return []
    rows: list[SourceInvariantViolation] = []
    for path in sorted(base.rglob("*.py")):
        for module, line in imports(path):
            if module == "noetrium_platform.composition" or module.startswith(
                "noetrium_platform.composition."
            ):
                rows.append(violation(
                    root,
                    path,
                    "execution_core_composition_dependency_direction",
                    line,
                    f"execution core imports outer composition module {module}; inject through an inner port instead",
                ))
    return rows


def audit_workflow_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows = _audit_workflow_dependency_direction(root)
    rows.extend(_audit_execution_core_composition_direction(root))
    runtime_root = root / "noetrium_platform" / "research" / "execution" / "workflow" / "runtime"
    if not runtime_root.exists():
        return rows
    rows.extend(_audit_dispatch_authority(root))

    dispatcher = runtime_root / "operation_dispatch.py"
    text = source_text(dispatcher) if dispatcher.exists() else ""
    for token in ("OperationRequest", "_executor.execute"):
        if token not in text:
            rows.append(violation(
                root,
                dispatcher,
                "workflow_operation_backbone",
                1,
                f"workflow Kernel dispatcher missing boundary token: {token}",
            ))

    effect_ops = root / "noetrium_platform" / "research" / "execution" / "workflow" / "runtime" / "effect_intents.py"
    rows.extend(_audit_required_operations(
        root,
        label="effect_intent_runtime",
        paths=(effect_ops,),
        required=_REQUIRED_EFFECT_INTENT_OPERATIONS,
    ))

    workflows = root / "noetrium_platform" / "composition" / "workflows"
    for family, required in _REQUIRED_WORKFLOW_OPERATIONS.items():
        base = workflows / family
        rows.extend(_audit_required_operations(
            root,
            label=f"workflow_{family}",
            paths=tuple(sorted(base.glob("*.py"))) if base.exists() else (),
            required=required,
        ))
    return rows


__all__ = ["audit_workflow_invariants"]
