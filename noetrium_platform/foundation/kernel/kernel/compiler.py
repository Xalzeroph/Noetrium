"""Canonical nsh/SDK program compiler projection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .canonical import canonical_digest, freeze_json, require_sha256
from .json_value import JsonValue
from .machine import MachineProgramRef, ProgramLock


@dataclass(frozen=True, slots=True)
class ProgramSource:
    program_kind: str
    program_version: str
    schema_id: str
    code: str
    dependencies: JsonValue = None
    schema: JsonValue = None
    data: JsonValue = None
    config: JsonValue = None

    def __post_init__(self) -> None:
        for name, value in (
            ("program_kind", self.program_kind),
            ("program_version", self.program_version),
            ("schema_id", self.schema_id),
            ("code", self.code),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"program source {name} is required")
        for name in ("dependencies", "schema", "data", "config"):
            object.__setattr__(self, name, freeze_json(getattr(self, name)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ProgramSource":
        if not isinstance(value, Mapping):
            raise TypeError("nsh source must be an object")
        return cls(
            value["program_kind"], value["program_version"], value["schema_id"],
            value["code"], value.get("dependencies"),
            value.get("schema"), value.get("data"), value.get("config"),
        )


@dataclass(frozen=True, slots=True)
class CompiledProgram:
    source: ProgramSource
    program: MachineProgramRef
    compiler_digest: str

    def manifest(self) -> dict[str, object]:
        lock = self.program.program_lock
        return {
            "program_digest": self.program.program_digest,
            "schema_id": self.program.schema_id,
            "program_kind": self.program.program_kind,
            "program_version": self.program.program_version,
            "program_lock": {
                "code_digest": lock.code_digest,
                "dependency_digest": lock.dependency_digest,
                "schema_digest": lock.schema_digest,
                "interpreter_digest": lock.interpreter_digest,
                "data_digest": lock.data_digest,
                "config_digest": lock.config_digest,
                "lock_digest": lock.lock_digest,
            },
            "compiler_digest": self.compiler_digest,
        }


class NshCompiler:
    """Compile declarative source into a portable, content-addressed program."""

    def __init__(self, *, interpreter_id: str, interpreter_version: str) -> None:
        if not interpreter_id.strip() or not interpreter_version.strip():
            raise ValueError("nsh interpreter identity is required")
        self.interpreter_digest = canonical_digest({
            "interpreter_id": interpreter_id,
            "interpreter_version": interpreter_version,
        })
        self.compiler_digest = canonical_digest({
            "compiler": "noetrium.nsh",
            "version": "1",
        })

    def compile(self, source: ProgramSource) -> CompiledProgram:
        if not isinstance(source, ProgramSource):
            raise TypeError("nsh compiler requires ProgramSource")
        lock = ProgramLock(
            code_digest=canonical_digest(source.code),
            dependency_digest=canonical_digest(source.dependencies),
            schema_digest=canonical_digest(source.schema),
            interpreter_digest=self.interpreter_digest,
            data_digest=canonical_digest(source.data),
            config_digest=canonical_digest(source.config),
        )
        program_digest = canonical_digest({
            "program_kind": source.program_kind,
            "program_version": source.program_version,
            "schema_id": source.schema_id,
            "program_lock": lock,
        })
        return CompiledProgram(
            source,
            MachineProgramRef(
                program_digest,
                source.schema_id,
                source.program_kind,
                source.program_version,
                lock,
            ),
            self.compiler_digest,
        )

    def verify_manifest(self, manifest: Mapping[str, object]) -> MachineProgramRef:
        if not isinstance(manifest, Mapping):
            raise TypeError("program manifest must be an object")
        lock_data = manifest.get("program_lock")
        if not isinstance(lock_data, Mapping):
            raise ValueError("program manifest requires program_lock")
        lock = ProgramLock(
            lock_data["code_digest"], lock_data["dependency_digest"],
            lock_data["schema_digest"], lock_data["interpreter_digest"],
            lock_data["data_digest"], lock_data["config_digest"],
        )
        given_lock = lock_data.get("lock_digest")
        if given_lock is not None and given_lock != lock.lock_digest:
            raise ValueError("program manifest lock_digest is not authoritative")
        program = MachineProgramRef(
            manifest["program_digest"],
            manifest["schema_id"],
            manifest["program_kind"],
            manifest["program_version"],
            lock,
        )
        expected = canonical_digest({
            "program_kind": program.program_kind,
            "program_version": program.program_version,
            "schema_id": program.schema_id,
            "program_lock": lock,
        })
        if expected != program.program_digest:
            raise ValueError("program manifest program_digest is not authoritative")
        return program


__all__ = ["CompiledProgram", "NshCompiler", "ProgramSource"]
