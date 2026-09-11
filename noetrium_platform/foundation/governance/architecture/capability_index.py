"""Derived capability index; source code remains the authority."""
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
    "METHOD": "method",
    "AGENT": "agent",
    "MEMORY": "memory",
    "ENVIRONMENT": "environment",
    "EVALUATION": "evaluation",
}


def _literal(node: ast.AST) -> object:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, bool, type(None))):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(item) for item in node.elts)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "MachineKind" and node.attr in _KIND_VALUES:
            return _KIND_VALUES[node.attr]
    raise ValueError("machine family descriptor must contain literal values")


def _machine_families(path: Path) -> tuple[dict[str, object], ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        (node for node in tree.body
         if isinstance(node, ast.FunctionDef) and node.name == "reference_machine_families"),
        None,
    )
    if function is None:
        raise ValueError("reference machine family function is missing")
    returned = next((node for node in function.body if isinstance(node, ast.Return)), None)
    if returned is None or not isinstance(returned.value, ast.Tuple):
        raise ValueError("reference machine family set must be a literal tuple")
    families: list[dict[str, object]] = []
    for item in returned.value.elts:
        if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Name) or item.func.id != "MachineFamilyDescriptor":
            raise ValueError("reference machine family set contains a non-descriptor")
        fields = {keyword.arg: _literal(keyword.value) for keyword in item.keywords if keyword.arg is not None}
        required = {"family_id", "kind", "implementation_version", "state_schema", "command_kinds"}
        if set(fields) - (required | {"replay_level", "required_capabilities", "provided_capabilities"}) or not required <= set(fields):
            raise ValueError("reference machine family descriptor fields are incomplete")
        payload = {
            "family_id": fields["family_id"],
            "kind": fields["kind"],
            "implementation_version": fields["implementation_version"],
            "state_schema": fields["state_schema"],
            "replay_level": fields.get("replay_level", "replayable"),
            "command_kinds": fields["command_kinds"],
            "required_capabilities": fields.get("required_capabilities", ()),
            "provided_capabilities": fields.get("provided_capabilities", ()),
        }
        payload["family_digest"] = canonical_digest(payload)
        families.append(payload)
    return tuple(families)


def _exports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "__all__"
                   for target in node.targets):
                if not isinstance(node.value, (ast.List, ast.Tuple)):
                    raise ValueError("kernel __all__ must be a literal sequence")
                values = tuple(
                    item.value for item in node.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
                if len(values) != len(node.value.elts):
                    raise ValueError("kernel __all__ contains non-text export")
                return tuple(sorted(values))
    raise ValueError("kernel __all__ is missing")


def build_capability_index(root: Path) -> dict[str, Any]:
    root = Path(root)
    kernel_path = root / "noetrium_platform/foundation/kernel/kernel/__init__.py"
    family_path = root / "noetrium_platform/research/execution/machines/reference.py"
    kernel_digest = canonical_digest(kernel_path.read_text(encoding="utf-8"))
    family_digest = canonical_digest(family_path.read_text(encoding="utf-8"))
    families = _machine_families(family_path)
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "source_files": {
            "kernel_exports": "noetrium_platform/foundation/kernel/kernel/__init__.py",
            "machine_families": "noetrium_platform/research/execution/machines/reference.py",
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


def write_capability_index(root: Path, output: Path) -> dict[str, Any]:
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


__all__ = ["SCHEMA", "build_capability_index", "load_capability_index", "write_capability_index"]
