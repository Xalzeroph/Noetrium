"""Canonical nsh/SDK Unit compiler projection."""
from __future__ import annotations

from dataclasses import dataclass

from .canonical import canonical_digest, freeze_json, require_sha256
from .json_value import JsonDocument, JsonInput, JsonValue
from .machine import ExecutableUnitRef, UnitExecutionLock


@dataclass(frozen=True, slots=True)
class UnitSource:
    domain: str
    version: str
    schema_id: str
    code: str
    dependency_manifest: JsonValue = None
    schema: JsonValue = None
    data: JsonValue = None
    config: JsonValue = None

    def __post_init__(self) -> None:
        for name, value in (
            ("domain", self.domain),
            ("version", self.version),
            ("schema_id", self.schema_id),
            ("code", self.code),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"Unit source {name} is required")
        for name in ("dependency_manifest", "schema", "data", "config"):
            object.__setattr__(self, name, freeze_json(getattr(self, name)))

    @classmethod
    def from_mapping(cls, value: JsonDocument) -> "UnitSource":
        if not isinstance(value, dict):
            raise TypeError("nsh source must be an object")
        return cls(
            value["domain"], value["version"], value["schema_id"],
            value["code"], value.get("dependencies"),
            value.get("schema"), value.get("data"), value.get("config"),
        )


@dataclass(frozen=True, slots=True)
class CompiledUnit:
    source: UnitSource
    unit: ExecutableUnitRef
    compiler_digest: str

    def manifest(self) -> dict[str, JsonInput]:
        lock = self.unit.execution_lock
        return {
            "unit_digest": self.unit.unit_digest,
            "state_schema": self.unit.state_schema,
            "domain": self.unit.domain,
            "version": self.unit.version,
            "execution_lock": {
                "code_digest": lock.code_digest,
                "dependency_digest": lock.dependency_digest,
                "schema_digest": lock.schema_digest,
                "unit_machine_digest": lock.unit_machine_digest,
                "data_digest": lock.data_digest,
                "config_digest": lock.config_digest,
                "lock_digest": lock.lock_digest,
            },
            "compiler_digest": self.compiler_digest,
        }


class UnitCompiler:
    """Compile declarative source into a portable, content-addressed Unit."""

    def __init__(self, *, unit_machine_id: str, unit_machine_version: str) -> None:
        if not unit_machine_id.strip() or not unit_machine_version.strip():
            raise ValueError("Unit machine identity is required")
        self.unit_machine_digest = canonical_digest({
            "unit_machine_id": unit_machine_id,
            "unit_machine_version": unit_machine_version,
        })
        self.compiler_digest = canonical_digest({
            "compiler": "noetrium.nsh",
            "version": "1",
        })

    def compile(self, source: UnitSource) -> CompiledUnit:
        if not isinstance(source, UnitSource):
            raise TypeError("Unit compiler requires UnitSource")
        lock = UnitExecutionLock(
            code_digest=canonical_digest(source.code),
            dependency_digest=canonical_digest(source.dependency_manifest),
            schema_digest=canonical_digest(source.schema),
            unit_machine_digest=self.unit_machine_digest,
            data_digest=canonical_digest(source.data),
            config_digest=canonical_digest(source.config),
        )
        unit_digest = canonical_digest({
            "domain": source.domain,
            "version": source.version,
            "state_schema": source.schema_id,
            "execution_lock": lock,
        })
        return CompiledUnit(
            source,
            ExecutableUnitRef(
                unit_digest,
                source.schema_id,
                source.domain,
                source.version,
                lock,
            ),
            self.compiler_digest,
        )

    def verify_manifest(self, manifest: JsonDocument) -> ExecutableUnitRef:
        if not isinstance(manifest, dict):
            raise TypeError("Unit manifest must be an object")
        lock_data = manifest.get("execution_lock")
        if not isinstance(lock_data, dict):
            raise ValueError("Unit manifest requires execution_lock")
        lock = UnitExecutionLock(
            lock_data["code_digest"], lock_data["dependency_digest"],
            lock_data["schema_digest"], lock_data["unit_machine_digest"],
            lock_data["data_digest"], lock_data["config_digest"],
        )
        given_lock = lock_data.get("lock_digest")
        if given_lock is not None and given_lock != lock.lock_digest:
            raise ValueError("Unit manifest lock_digest is not authoritative")
        unit = ExecutableUnitRef(
            manifest["unit_digest"],
            manifest["state_schema"],
            manifest["domain"],
            manifest["version"],
            lock,
        )
        expected = canonical_digest({
            "domain": unit.domain,
            "version": unit.version,
            "state_schema": unit.state_schema,
            "execution_lock": lock,
        })
        if expected != unit.unit_digest:
            raise ValueError("Unit manifest unit_digest is not authoritative")
        return unit


__all__ = ["CompiledUnit", "UnitCompiler", "UnitSource"]
