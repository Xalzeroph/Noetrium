from __future__ import annotations

"""Physical executor for typed Minecraft task world operations."""

from dataclasses import dataclass
import hashlib
from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import MinecraftServerConsolePort, normalize_minecraft_world_ops


def _relative(value: int) -> str:
    return "~" if value == 0 else f"~{value}"


def _coords(values: object, *, relative: bool) -> str:
    rows = tuple(int(value) for value in values)  # normalized upstream
    return " ".join(_relative(value) if relative else str(value) for value in rows)


def minecraft_world_op_command(value: Mapping[str, object]) -> str:
    kind = str(value["kind"])
    anchor = str(value.get("anchor", "agent"))
    prefix = "execute at ResearchBot run " if anchor == "agent" else ""
    relative = anchor == "agent"
    if kind == "fill":
        return (
            prefix
            + "fill "
            + _coords(value["start"], relative=relative)
            + " "
            + _coords(value["end"], relative=relative)
            + " minecraft:"
            + str(value["block"])
        )
    if kind == "set_block":
        return (
            prefix
            + "setblock "
            + _coords(value["position"], relative=relative)
            + " minecraft:"
            + str(value["block"])
        )
    if kind == "summon":
        return (
            prefix
            + "summon minecraft:"
            + str(value["entity"])
            + " "
            + _coords(value["position"], relative=relative)
        )
    if kind == "effect":
        return (
            "effect give ResearchBot minecraft:"
            + str(value["effect"])
            + " "
            + str(value["duration_seconds"])
            + " "
            + str(value["amplifier"])
            + " "
            + ("true" if bool(value["hide_particles"]) else "false")
        )
    raise ValueError(f"unsupported Minecraft world operation kind: {kind!r}")


@dataclass(frozen=True, slots=True)
class MinecraftWorldOperationReceipt:
    operation_id: str
    operation_digest: str
    command_evidence_ref: str
    command_response_sha256: str


@dataclass(frozen=True, slots=True)
class MinecraftWorldSetupReceipt:
    operations_digest: str
    operations: tuple[MinecraftWorldOperationReceipt, ...]


class RconMinecraftWorldSetupProvisioner:
    """Compile typed setup semantics inside the provider and retain evidence."""

    def __init__(self, console: MinecraftServerConsolePort, operations: object) -> None:
        self.console = console
        self.operations = normalize_minecraft_world_ops(operations)

    def apply(self, *, timeout_s: float = 10.0) -> MinecraftWorldSetupReceipt:
        if timeout_s <= 0:
            raise ValueError("Minecraft world setup timeout must be positive")
        receipts: list[MinecraftWorldOperationReceipt] = []
        for operation in self.operations:
            command = minecraft_world_op_command(operation)
            # Mutation commands are exactly-once at this layer. RCON response
            # text is wire evidence, not physical-state truth; an empty response
            # must never cause a non-idempotent world operation (for example
            # summon) to be replayed. Physical convergence is established by the
            # independent Mineflayer setup verifier after all mutations complete.
            result = self.console.execute(command, timeout_s=timeout_s)
            lowered = result.response.casefold()
            if any(marker in lowered for marker in (
                "unknown or incomplete command",
                "incorrect argument",
                "no entity was found",
                "expected ",
            )):
                raise RuntimeError(
                    "Minecraft typed world setup command rejected: "
                    f"operation={operation['operation_id']}; response={result.response[:240]!r}"
                )
            receipts.append(MinecraftWorldOperationReceipt(
                operation_id=str(operation["operation_id"]),
                operation_digest=canonical_digest(operation),
                command_evidence_ref=result.evidence_ref,
                command_response_sha256=hashlib.sha256(
                    result.response.encode("utf-8")
                ).hexdigest(),
            ))
        return MinecraftWorldSetupReceipt(
            operations_digest=canonical_digest(self.operations),
            operations=tuple(receipts),
        )


__all__ = [
    "MinecraftWorldOperationReceipt",
    "MinecraftWorldSetupReceipt",
    "RconMinecraftWorldSetupProvisioner",
    "minecraft_world_op_command",
]
