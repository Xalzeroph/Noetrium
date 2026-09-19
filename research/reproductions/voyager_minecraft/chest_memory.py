from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    MemoryConcern,
    MemoryProgramBuilder,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
)

from .fidelity import VOYAGER_AUDITED_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class VoyagerChestEntry:
    position: str
    value: JsonValue
    entry_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "position",
            _text(self.position, "Voyager chest position"),
        )
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(
            self,
            "entry_digest",
            canonical_digest({
                "position": self.position,
                "value": thaw_json(self.value),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "position": self.position,
            "value": self.value,
            "entry_digest": self.entry_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VoyagerChestEntry":
        if not isinstance(value, Mapping):
            raise TypeError("Voyager chest entry must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("Voyager chest entry must decode to an object")
        entry = cls(
            position=decoded.get("position"),
            value=decoded.get("value"),
        )
        supplied = decoded.get("entry_digest")
        if supplied is not None and supplied != entry.entry_digest:
            raise ValueError("Voyager chest entry digest mismatch")
        return entry


def voyager_chest_memory_initial_data() -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "entries": (),
        "sequence": 0,
        "result": None,
    }


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.payload)
    if not isinstance(decoded, dict):
        raise TypeError("Voyager chest-memory payload must be an object")
    return decoded


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    decoded = thaw_json(request.data)
    if not isinstance(decoded, dict):
        raise TypeError("Voyager chest-memory data must be an object")
    if decoded.get("source_commit") != VOYAGER_AUDITED_COMMIT:
        raise ValueError("Voyager chest-memory source identity drifted")
    return decoded


def _entries(value: object) -> tuple[VoyagerChestEntry, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("Voyager chest entries must be a sequence")
    return tuple(VoyagerChestEntry.from_payload(row) for row in value)


def _render(entries: tuple[VoyagerChestEntry, ...]) -> str:
    if not entries:
        return "Chests: None\n\n"
    rows: list[str] = []
    for entry in entries:
        value = thaw_json(entry.value)
        if isinstance(value, dict):
            rows.append(
                f"{entry.position}: {value}" if value else f"{entry.position}: Empty"
            )
        elif isinstance(value, str):
            if value != "Unknown":
                raise ValueError(
                    "paper-era Voyager string chest state must be 'Unknown'"
                )
            rows.append(f"{entry.position}: Unknown items inside")
        else:
            raise TypeError(
                "paper-era Voyager chest state must be object or 'Unknown'"
            )
    return "Chests:\n" + "\n".join(rows) + "\n\n"


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    del binding
    data = _data(request)
    envelope = _payload(request)
    event = envelope.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("Voyager chest-memory requires event envelope")
    kind = _text(event.get("kind"), "Voyager chest-memory event kind")
    event_payload = event.get("payload", {})
    if not isinstance(event_payload, Mapping):
        raise TypeError("Voyager chest-memory event payload must be an object")
    payload = dict(thaw_json(event_payload))
    entries = list(_entries(data.get("entries", ())))
    sequence = data.get("sequence", 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Voyager chest-memory sequence is invalid")

    if kind == "voyager.chest.update":
        chests = payload.get("chests")
        if not isinstance(chests, Mapping):
            raise TypeError("Voyager chest update requires chests object")
        index = {entry.position: i for i, entry in enumerate(entries)}
        changed: list[str] = []
        for raw_position, raw_value in chests.items():
            position = _text(raw_position, "Voyager chest position")
            current_index = index.get(position)
            if current_index is None:
                entry = VoyagerChestEntry(position, raw_value)
                entries.append(entry)
                index[position] = len(entries) - 1
                changed.append(position)
                continue
            if isinstance(raw_value, Mapping):
                entries[current_index] = VoyagerChestEntry(
                    position,
                    dict(raw_value),
                )
                changed.append(position)
        frozen_entries = tuple(entries)
        result = {
            "changed_positions": tuple(changed),
            "entry_count": len(frozen_entries),
            "rendered": _render(frozen_entries),
            "memory_digest": canonical_digest(
                tuple(entry.entry_digest for entry in frozen_entries)
            ),
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "entries": tuple(entry.payload() for entry in frozen_entries),
                "sequence": sequence + 1,
                "result": result,
            },
            events=({
                "type": "voyager_chest_memory_updated",
                "changed_positions": tuple(changed),
                "entry_count": len(frozen_entries),
                "memory_digest": result["memory_digest"],
            },),
        )

    if kind == "voyager.chest.read":
        frozen_entries = tuple(entries)
        result = {
            "entries": tuple(entry.payload() for entry in frozen_entries),
            "entry_count": len(frozen_entries),
            "rendered": _render(frozen_entries),
            "memory_digest": canonical_digest(
                tuple(entry.entry_digest for entry in frozen_entries)
            ),
        }
        return ProgramNodeResult(
            value=result,
            state_update={"result": result},
            events=({
                "type": "voyager_chest_memory_read",
                "entry_count": len(frozen_entries),
                "memory_digest": result["memory_digest"],
            },),
        )

    raise ValueError(f"unsupported Voyager chest-memory event: {kind}")


def build_voyager_chest_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="voyager.chest-memory",
            version=VOYAGER_AUDITED_COMMIT[:12],
            state_schema="voyager.chest-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "voyager.chest-memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.PROJECTION.value,
                ),
                "source_commit": VOYAGER_AUDITED_COMMIT,
            },
            next_node="dispatch",
        )
        .build()
    )


VOYAGER_CHEST_MEMORY_PROGRAM = build_voyager_chest_memory_program()


def voyager_chest_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "voyager.chest-memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "voyager.chest-memory.dispatch",
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def voyager_chest_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="voyager.chest-memory",
        program=VOYAGER_CHEST_MEMORY_PROGRAM,
        operations=voyager_chest_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": VOYAGER_AUDITED_COMMIT,
            "paper_semantics": "action-agent-chest-memory-v1",
        },
    )


__all__ = [
    "VOYAGER_CHEST_MEMORY_PROGRAM",
    "VoyagerChestEntry",
    "build_voyager_chest_memory_program",
    "voyager_chest_memory_host",
    "voyager_chest_memory_initial_data",
    "voyager_chest_memory_operations",
]
