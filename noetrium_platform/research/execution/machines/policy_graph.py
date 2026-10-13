"""One graph schema for immutable Machine policy programs.

Policy structure is data. Runtime registries/deciders remain behavioral authorities.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest

MACHINE_POLICY_TRAIT = "machine.policy"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def machine_policy_graph(
    *,
    policy_trait: str,
    program_id: str,
    version: str,
    parameters: Mapping[str, JsonValue],
) -> NoetriumUnit:
    policy_trait = _text(policy_trait, "machine policy trait")
    program_id = _text(program_id, "machine policy program_id")
    version = _text(version, "machine policy version")
    if not isinstance(parameters, Mapping):
        raise TypeError("machine policy parameters must be an object")
    return structure_unit(
        "machine-policy:" + canonical_digest((policy_trait, program_id))[:24],
        traits=(MACHINE_POLICY_TRAIT, policy_trait),
        parameters={"program_id": program_id, "version": version, **dict(parameters)},
    )


def require_machine_policy(graph: NoetriumUnit, policy_trait: str) -> NoetriumUnit:
    if type(graph) is not NoetriumUnit or not graph.has_trait(MACHINE_POLICY_TRAIT) or not graph.has_trait(policy_trait):
        raise TypeError(f"machine policy must be {policy_trait} NoetriumUnit")
    return graph


def policy_text(graph: NoetriumUnit, policy_trait: str, name: str) -> str:
    require_machine_policy(graph, policy_trait)
    return _text(graph.parameters.get(name), f"{policy_trait} {name}")


def policy_program_id(graph: NoetriumUnit, policy_trait: str) -> str:
    return policy_text(graph, policy_trait, "program_id")


def policy_version(graph: NoetriumUnit, policy_trait: str) -> str:
    return policy_text(graph, policy_trait, "version")


def policy_digest(graph: NoetriumUnit, policy_trait: str) -> str:
    require_machine_policy(graph, policy_trait)
    return graph.semantic_digest


__all__ = [
    "MACHINE_POLICY_TRAIT",
    "machine_policy_graph",
    "policy_digest",
    "policy_program_id",
    "policy_text",
    "policy_version",
    "require_machine_policy",
]
