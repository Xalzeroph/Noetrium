"""Derived capability index; source code remains the authority.

The programmable research-Machine inventory is derived from the current
ResearchProgram source constants rather than a retired reference interpreter.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from noetrium_platform.foundation.kernel.kernel.canonical import (
    canonical_bytes,
    canonical_digest,
    strict_json_loads,
)

SCHEMA = "noetrium.capability-index.v1"
_KIND_VALUES = {
    "EXPERIMENT": "experiment",
    "RUN": "run",
    "RUNTIME": "runtime",
    "PARTICIPANT": "participant",
    "MEMORY": "memory",
    "ENVIRONMENT": "environment",
    "EVALUATION": "evaluation",
    "OPTIMIZATION": "optimization",
}


def _literal(node: ast.AST) -> object:
    if isinstance(
        node,
        ast.Constant,
    ) and isinstance(node.value, (str, int, bool, type(None))):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(item) for item in node.elts)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "MachineKind" and node.attr in _KIND_VALUES:
            return _KIND_VALUES[node.attr]
    raise ValueError(
        "programmable Machine declaration must contain literal values"
    )


def _assignment(tree: ast.Module, name: str) -> ast.AST:
    matches: list[ast.AST] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        else:
            targets = (node.target,)
            value = node.value
        if value is None:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in targets
        ):
            matches.append(value)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one programmable Machine declaration for {name}"
        )
    return matches[0]


def _machine_families(path: Path) -> tuple[dict[str, object], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "programmable_machine_family"
        ),
        None,
    )
    if function is None:
        raise ValueError("programmable Machine family function is missing")

    commands = _literal(_assignment(tree, "PROGRAM_COMMANDS"))
    kinds = _literal(_assignment(tree, "PROGRAMMABLE_MACHINE_KINDS"))
    family_version = _literal(
        _assignment(tree, "PROGRAMMABLE_MACHINE_FAMILY_VERSION")
    )
    state_schema_version = _literal(
        _assignment(tree, "PROGRAMMABLE_MACHINE_STATE_SCHEMA_VERSION")
    )

    if (
        not isinstance(commands, tuple)
        or not commands
        or any(type(value) is not str or not value for value in commands)
    ):
        raise ValueError("PROGRAM_COMMANDS must be a non-empty text tuple")
    if (
        not isinstance(kinds, tuple)
        or not kinds
        or any(type(value) is not str or value not in _KIND_VALUES.values()
                for value in kinds)
    ):
        raise ValueError(
            "PROGRAMMABLE_MACHINE_KINDS contains unsupported MachineKind"
        )
    if len(kinds) != len(set(kinds)):
        raise ValueError("PROGRAMMABLE_MACHINE_KINDS contains duplicates")
    if type(family_version) is not str or not family_version:
        raise ValueError(
            "PROGRAMMABLE_MACHINE_FAMILY_VERSION must be non-empty text"
        )
    if type(state_schema_version) is not str or not state_schema_version:
        raise ValueError(
            "PROGRAMMABLE_MACHINE_STATE_SCHEMA_VERSION must be non-empty text"
        )

    families: list[dict[str, object]] = []
    for kind in kinds:
        payload: dict[str, object] = {
            "family_id": f"{kind}.program.v{family_version}",
            "kind": kind,
            "implementation_version": family_version,
            "state_schema": (
                f"{kind}.program-state.v{state_schema_version}"
            ),
            "replay_level": "replayable",
            "command_kinds": commands,
            "required_capabilities": (),
            "provided_capabilities": (),
        }
        payload["family_digest"] = canonical_digest(payload)
        families.append(payload)
    return tuple(families)


def _exports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                if not isinstance(node.value, (ast.List, ast.Tuple)):
                    raise ValueError("kernel __all__ must be a literal sequence")
                values = tuple(
                    item.value
                    for item in node.value.elts
                    if isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                )
                if len(values) != len(node.value.elts):
                    raise ValueError(
                        "kernel __all__ contains non-text export"
                    )
                return tuple(sorted(values))
    raise ValueError("kernel __all__ is missing")


def build_capability_index(root: Path) -> dict[str, Any]:
    root = Path(root)
    kernel_path = (
        root / "noetrium_platform/foundation/kernel/kernel/__init__.py"
    )
    family_path = (
        root / "noetrium_platform/research/execution/machines/program.py"
    )
    kernel_digest = canonical_digest(
        kernel_path.read_text(encoding="utf-8")
    )
    family_digest = canonical_digest(
        family_path.read_text(encoding="utf-8")
    )
    families = _machine_families(family_path)
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "source_files": {
            "kernel_exports": (
                "noetrium_platform/foundation/kernel/kernel/__init__.py"
            ),
            "machine_families": (
                "noetrium_platform/research/execution/machines/program.py"
            ),
        },
        "source_digest": canonical_digest({
            "kernel": kernel_digest,
            "families": family_digest,
        }),
        "kernel_exports": _exports(kernel_path),
        "machine_families": families,
    }
    value["index_digest"] = canonical_digest(value)
    return value


def write_capability_index(
    root: Path,
    output: Path,
) -> dict[str, Any]:
    value = build_capability_index(root)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_bytes(canonical_bytes(value))
    return value


def load_capability_index(path: Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    value = strict_json_loads(raw)
    if canonical_bytes(value) != raw or not isinstance(value, dict):
        raise ValueError("capability index is not canonical")
    expected_digest = value.get("index_digest")
    body = dict(value)
    body.pop("index_digest", None)
    if expected_digest != canonical_digest(body):
        raise ValueError("capability index digest mismatch")
    return value


__all__ = [
    "SCHEMA",
    "build_capability_index",
    "load_capability_index",
    "write_capability_index",
]
