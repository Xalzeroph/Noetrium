"""Typed execution contracts for capabilities, attempts, bindings and child machines.

These records carry identity and policy only; they never own mutable machine state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .canonical import canonical_digest, require_sha256
from .json_value import JsonObject


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


def _tuple_text(values: object, name: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(v) is not str or not v.strip() for v in values):
        raise TypeError(f"{name} must be a tuple of non-empty text")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    return values


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    provider_version: str
    input_schema: str
    output_schema: str
    effect_class: str
    permission_scope: tuple[str, ...]
    resource_budget: JsonObject = field(default_factory=dict)
    idempotency_policy: str = "unknown"
    evidence_policy: str = "required"
    descriptor_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("capability_id", self.capability_id),
            ("provider_version", self.provider_version),
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
            ("effect_class", self.effect_class),
            ("idempotency_policy", self.idempotency_policy),
            ("evidence_policy", self.evidence_policy),
        ):
            _text(value, f"capability {name}")
        _tuple_text(self.permission_scope, "capability permission_scope")
        if type(self.resource_budget) is not dict:
            raise TypeError("capability resource_budget must be an object")
        object.__setattr__(self, "resource_budget", dict(self.resource_budget))
        object.__setattr__(
            self, "descriptor_digest",
            canonical_digest({
                "capability_id": self.capability_id,
                "provider_version": self.provider_version,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "effect_class": self.effect_class,
                "permission_scope": self.permission_scope,
                "resource_budget": self.resource_budget,
                "idempotency_policy": self.idempotency_policy,
                "evidence_policy": self.evidence_policy,
            }),
        )


@dataclass(frozen=True, slots=True)
class MachineAttempt:
    attempt_id: str
    command_id: str
    worker_id: str
    authority_epoch: int | None
    attempt_digest: str = field(init=False)
    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        _text(self.command_id, "command_id")
        _text(self.worker_id, "worker_id")
        if self.authority_epoch is not None and (
            type(self.authority_epoch) is not int or self.authority_epoch < 0
        ):
            raise ValueError("attempt authority_epoch must be non-negative")
        object.__setattr__(
            self, "attempt_digest",
            canonical_digest({
                "attempt_id": self.attempt_id,
                "command_id": self.command_id,
                "worker_id": self.worker_id,
                "authority_epoch": self.authority_epoch,
            }),
        )


@dataclass(frozen=True, slots=True)
class RunBinding:
    kernel_abi_version: str
    machine_implementation_digest: str
    program_digest: str
    capability_provider_versions: tuple[tuple[str, str], ...]
    schema_versions: tuple[str, ...]
    environment_version: str
    policy_version: str
    binding_digest: str = field(init=False)
    def __post_init__(self) -> None:
        _text(self.kernel_abi_version, "kernel_abi_version")
        _text(self.environment_version, "environment_version")
        _text(self.policy_version, "policy_version")
        require_sha256(self.machine_implementation_digest, "machine_implementation_digest")
        require_sha256(self.program_digest, "program_digest")
        if type(self.capability_provider_versions) is not tuple:
            raise TypeError("capability_provider_versions must be a tuple")
        for item in self.capability_provider_versions:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("provider version binding must be a pair")
            _text(item[0], "provider identity")
            _text(item[1], "provider version")
        _tuple_text(self.schema_versions, "schema_versions")
        object.__setattr__(
            self, "binding_digest",
            canonical_digest({
                "kernel_abi_version": self.kernel_abi_version,
                "machine_implementation_digest": self.machine_implementation_digest,
                "program_digest": self.program_digest,
                "capability_provider_versions": self.capability_provider_versions,
                "schema_versions": self.schema_versions,
                "environment_version": self.environment_version,
                "policy_version": self.policy_version,
            }),
        )


@dataclass(frozen=True, slots=True)
class ChildMachineLink:
    parent_machine_id: str
    child_machine_id: str
    child_program_digest: str
    child_snapshot_ref: str
    child_transition_start: int
    child_transition_end: int
    child_result_ref: str | None
    failure_policy: str
    link_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("parent_machine_id", self.parent_machine_id),
            ("child_machine_id", self.child_machine_id),
            ("child_snapshot_ref", self.child_snapshot_ref),
            ("failure_policy", self.failure_policy),
        ):
            _text(value, f"child link {name}")
        require_sha256(self.child_program_digest, "child_program_digest")
        if type(self.child_transition_start) is not int or self.child_transition_start < 0:
            raise ValueError("child transition start must be non-negative")
        if type(self.child_transition_end) is not int or (
            self.child_transition_end < self.child_transition_start
        ):
            raise ValueError("child transition range is invalid")
        if self.child_result_ref is not None:
            _text(self.child_result_ref, "child_result_ref")
        object.__setattr__(self, "link_digest", canonical_digest({
            "parent_machine_id": self.parent_machine_id,
            "child_machine_id": self.child_machine_id,
            "child_program_digest": self.child_program_digest,
            "child_snapshot_ref": self.child_snapshot_ref,
            "child_transition_start": self.child_transition_start,
            "child_transition_end": self.child_transition_end,
            "child_result_ref": self.child_result_ref,
            "failure_policy": self.failure_policy,
        }))

    def as_dict(self) -> dict[str, object]:
        return {
            "parent_machine_id": self.parent_machine_id,
            "child_machine_id": self.child_machine_id,
            "child_program_digest": self.child_program_digest,
            "child_snapshot_ref": self.child_snapshot_ref,
            "child_transition_start": self.child_transition_start,
            "child_transition_end": self.child_transition_end,
            "child_result_ref": self.child_result_ref,
            "failure_policy": self.failure_policy,
            "link_digest": self.link_digest,
        }


__all__ = ["CapabilityDescriptor", "ChildMachineLink", "MachineAttempt", "RunBinding"]
