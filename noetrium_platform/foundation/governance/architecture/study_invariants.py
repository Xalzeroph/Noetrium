from __future__ import annotations

import ast
from pathlib import Path

from .source_index import source_text, source_tree

from .source_scan import SourceInvariantViolation, imports, violation

_REQUIRED_RUN_CHECKPOINT_OPERATIONS = (
    "run.checkpoint.publish",
    "run.checkpoint.load",
)


def _python_files(base: Path) -> tuple[Path, ...]:
    return tuple(sorted(base.rglob("*.py"))) if base.exists() else ()


def _literal_operation_types(paths: tuple[Path, ...]) -> frozenset[str]:
    operations: set[str] = set()
    for path in paths:
        tree = source_tree(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "operation_type" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    operations.add(keyword.value.value)
    return frozenset(operations)


def _audit_study_definition_boundary(root: Path) -> list[SourceInvariantViolation]:
    study = root / "noetrium_platform" / "research" / "experimentation" / "study"
    rows: list[SourceInvariantViolation] = []
    forbidden = (
        "noetrium_platform.capabilities.participant",
        "noetrium_platform.research.execution",
        "noetrium_platform.composition",
        "noetrium_platform.infrastructure.lifecycle",
        "noetrium_platform.capabilities.model",
    )
    for path in _python_files(study):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "study_definition_boundary",
                    line,
                    f"Study is a research grouping definition and cannot depend on runtime subsystem {module}",
                ))
    return rows


def _audit_experiment_runtime_boundary(root: Path) -> list[SourceInvariantViolation]:
    experiment = root / "noetrium_platform" / "research" / "experimentation" / "experiment"
    rows: list[SourceInvariantViolation] = []
    forbidden = (
        "noetrium_platform.capabilities.participant.definition.runtime",
        "noetrium_platform.capabilities.participant.binding.runtime",
        "noetrium_platform.capabilities.participant.session.runtime",
        "noetrium_platform.composition",
    )
    for path in _python_files(experiment):
        for module, line in imports(path):
            if module.startswith(forbidden):
                rows.append(violation(
                    root,
                    path,
                    "experiment_runtime_implementation_boundary",
                    line,
                    f"Experiment runtime imports concrete implementation/wiring {module}; compose dependencies externally",
                ))
    return rows


def _audit_checkpoint_operation_backbone(root: Path) -> list[SourceInvariantViolation]:
    checkpoint = root / "noetrium_platform" / "research" / "experimentation" / "checkpoint"
    rows: list[SourceInvariantViolation] = []
    if not checkpoint.exists():
        return rows
    operations = _literal_operation_types(_python_files(checkpoint))
    for operation_type in _REQUIRED_RUN_CHECKPOINT_OPERATIONS:
        if operation_type not in operations:
            rows.append(violation(
                root,
                checkpoint,
                "run_checkpoint_operation_backbone",
                1,
                f"missing required Run checkpoint operation boundary: {operation_type}",
            ))
    return rows


def _audit_participant_operation_backbone(root: Path) -> list[SourceInvariantViolation]:
    operations = root / "noetrium_platform" / "research" / "execution" / "participants"
    contract = root / "noetrium_platform" / "capabilities" / "participant" / "core" / "api" / "runtime_operations.py"
    rows: list[SourceInvariantViolation] = []
    if not contract.exists() and not operations.exists():
        return rows
    contract_text = source_text(contract) if contract.exists() else ""
    owners = {
        "resolve": operations / "resolution.py",
        "open_session": operations / "session_lifecycle.py",
        "close": operations / "session_lifecycle.py",
        "checkpoint": operations / "checkpoint_operations.py",
        "restore": operations / "checkpoint_operations.py",
    }
    for verb, owner in owners.items():
        if f'"{verb}"' not in contract_text:
            rows.append(violation(root, contract, "participant_runtime_operation_abi", 1, f"participant lifecycle ABI missing verb: {verb}"))
            continue
        if not owner.exists():
            rows.append(violation(root, owner, "participant_runtime_operation_abi", 1, f"participant lifecycle operation owner missing: {verb}"))
            continue
        tree = source_tree(owner)
        found = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "participant_operation_type"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == verb
            for node in ast.walk(tree)
        )
        if not found:
            rows.append(violation(root, owner, "participant_runtime_operation_abi", 1, f"participant operation boundary missing verb={verb}"))
    return rows


def audit_study_invariants(root: Path) -> list[SourceInvariantViolation]:
    root = Path(root).resolve()
    return (
        _audit_study_definition_boundary(root)
        + _audit_experiment_runtime_boundary(root)
        + _audit_checkpoint_operation_backbone(root)
        + _audit_participant_operation_backbone(root)
    )


__all__ = ["audit_study_invariants"]
