from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_digest,
    freeze_json,
    require_sha256,
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

from .fidelity import VOYAGER_AUDITED_COMMIT, VOYAGER_MINECRAFT_FIDELITY


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class VoyagerSkill:
    name: str
    code: str
    description: str
    revision: int = 1
    supersedes_digest: str | None = None
    skill_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("name", "code", "description"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), f"Voyager skill {name}"),
            )
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Voyager skill revision must be positive")
        if self.supersedes_digest is not None:
            object.__setattr__(
                self,
                "supersedes_digest",
                require_sha256(
                    self.supersedes_digest,
                    "Voyager supersedes_digest",
                ),
            )
        object.__setattr__(
            self,
            "skill_digest",
            canonical_digest({
                "name": self.name,
                "code": self.code,
                "description": self.description,
                "revision": self.revision,
                "supersedes_digest": self.supersedes_digest,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "revision": self.revision,
            "supersedes_digest": self.supersedes_digest,
            "skill_digest": self.skill_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VoyagerSkill":
        if not isinstance(value, Mapping):
            raise TypeError("Voyager skill payload must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("Voyager skill payload must decode to an object")
        skill = cls(
            name=decoded.get("name"),
            code=decoded.get("code"),
            description=decoded.get("description"),
            revision=decoded.get("revision", 1),
            supersedes_digest=decoded.get("supersedes_digest"),
        )
        supplied = decoded.get("skill_digest")
        if supplied is not None and require_sha256(
            supplied,
            "Voyager skill_digest",
        ) != skill.skill_digest:
            raise ValueError("Voyager skill digest mismatch")
        return skill


@dataclass(frozen=True, slots=True)
class VoyagerSkillDescriptionRequest:
    program_name: str
    program_code: str


@runtime_checkable
class VoyagerSkillDescriptionPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def describe(self, request: VoyagerSkillDescriptionRequest) -> str: ...


@dataclass(frozen=True, slots=True)
class VoyagerSkillRankRequest:
    query: str
    skills: tuple[VoyagerSkill, ...]
    limit: int


@dataclass(frozen=True, slots=True)
class VoyagerSkillRankResult:
    names: tuple[str, ...]
    scores: tuple[float, ...]
    receipt: JsonValue = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.names) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.names
        ):
            raise TypeError("Voyager rank names must be a text tuple")
        if len(self.names) != len(set(self.names)):
            raise ValueError("Voyager rank names must be unique")
        if type(self.scores) is not tuple or len(self.scores) != len(self.names):
            raise TypeError("Voyager rank scores must align with names")
        if any(type(value) not in (int, float) for value in self.scores):
            raise TypeError("Voyager rank scores must be numeric")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "result_digest",
            canonical_digest({
                "names": self.names,
                "scores": self.scores,
                "receipt": thaw_json(self.receipt),
            }),
        )


@runtime_checkable
class VoyagerSkillRetrieverPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def rank(self, request: VoyagerSkillRankRequest) -> VoyagerSkillRankResult: ...


@dataclass(frozen=True, slots=True)
class VoyagerSkillMemoryBinding:
    descriptions: VoyagerSkillDescriptionPort
    retriever: VoyagerSkillRetrieverPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.descriptions, VoyagerSkillDescriptionPort):
            raise TypeError(
                "Voyager skill memory requires description generator port"
            )
        if not isinstance(self.retriever, VoyagerSkillRetrieverPort):
            raise TypeError("Voyager skill memory requires retrieval port")
        description_digest = require_sha256(
            self.descriptions.identity_digest,
            "Voyager description port identity_digest",
        )
        retrieval_digest = require_sha256(
            self.retriever.identity_digest,
            "Voyager retrieval port identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "description_port_identity_digest": description_digest,
                "retrieval_port_identity_digest": retrieval_digest,
            }),
        )


def voyager_skill_memory_initial_data() -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "retrieval_top_k": VOYAGER_MINECRAFT_FIDELITY.skill_retrieval_top_k,
        "sequence": 0,
        "active_skills": (),
        "skill_history": (),
        "result": None,
    }


def _payload(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("Voyager skill-memory payload must be an object")
    return value


def _data(request: ProgramNodeRequest) -> dict[str, object]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("Voyager skill-memory data must be an object")
    if value.get("source_commit") != VOYAGER_AUDITED_COMMIT:
        raise ValueError("Voyager skill-memory source identity drifted")
    return value


def _skills(value: object) -> tuple[VoyagerSkill, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError("Voyager skill collection must be a sequence")
    return tuple(VoyagerSkill.from_payload(row) for row in value)


def _dispatch(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, VoyagerSkillMemoryBinding):
        raise TypeError(
            "Voyager skill-memory dispatch requires VoyagerSkillMemoryBinding"
        )
    data = _data(request)
    envelope = _payload(request)
    event = envelope.get("event")
    if not isinstance(event, Mapping):
        raise TypeError("Voyager skill-memory requires event envelope")
    kind = _text(event.get("kind"), "Voyager skill-memory event kind")
    event_payload = event.get("payload", {})
    if not isinstance(event_payload, Mapping):
        raise TypeError("Voyager skill-memory event payload must be an object")
    payload = dict(thaw_json(event_payload))

    if kind == "voyager.skill.write":
        name = _text(payload.get("program_name"), "Voyager program_name")
        code = _text(payload.get("program_code"), "Voyager program_code")
        description = binding.descriptions.describe(
            VoyagerSkillDescriptionRequest(name, code)
        )
        description = _text(description, "Voyager skill description")

        active = list(_skills(data.get("active_skills", ())))
        history = list(_skills(data.get("skill_history", ())))
        current = next((row for row in active if row.name == name), None)
        revision = 1 if current is None else current.revision + 1
        skill = VoyagerSkill(
            name=name,
            code=code,
            description=description,
            revision=revision,
            supersedes_digest=None if current is None else current.skill_digest,
        )
        active = [row for row in active if row.name != name]
        active.append(skill)
        active.sort(key=lambda row: row.name)
        history.append(skill)

        sequence = data.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            raise ValueError("Voyager skill-memory sequence is invalid")
        result = {
            "program_name": skill.name,
            "skill_digest": skill.skill_digest,
            "revision": skill.revision,
            "description": skill.description,
            "supersedes_digest": skill.supersedes_digest,
            "active_skill_count": len(active),
            "skill_history_count": len(history),
        }
        return ProgramNodeResult(
            value=result,
            state_update={
                "sequence": sequence + 1,
                "active_skills": tuple(row.payload() for row in active),
                "skill_history": tuple(row.payload() for row in history),
                "result": result,
            },
            events=({
                "type": "voyager_skill_written",
                "program_name": skill.name,
                "revision": skill.revision,
                "skill_digest": skill.skill_digest,
                "supersedes_digest": skill.supersedes_digest,
            },),
        )

    if kind == "voyager.skill.retrieve":
        query = _text(payload.get("query"), "Voyager skill retrieval query")
        configured_top_k = data.get("retrieval_top_k")
        if type(configured_top_k) is not int or configured_top_k < 1:
            raise ValueError("Voyager retrieval_top_k is invalid")
        requested_limit = payload.get("limit", configured_top_k)
        if type(requested_limit) is not int or requested_limit < 1:
            raise ValueError("Voyager retrieval limit must be positive")
        limit = min(requested_limit, configured_top_k)

        skills = _skills(data.get("active_skills", ()))
        if not skills:
            retrieval_digest = canonical_digest({
                "query": query,
                "program_names": (),
                "scores": (),
            })
            result = {
                "query": query,
                "program_names": (),
                "program_codes": (),
                "skill_digests": (),
                "scores": (),
                "retrieval_digest": retrieval_digest,
            }
            return ProgramNodeResult(
                value=result,
                state_update={"result": result},
                events=({
                    "type": "voyager_skills_retrieved",
                    "query_digest": canonical_digest(query),
                    "program_names": (),
                    "retrieval_digest": retrieval_digest,
                },),
            )

        ranked = binding.retriever.rank(
            VoyagerSkillRankRequest(
                query=query,
                skills=skills,
                limit=min(limit, len(skills)),
            )
        )
        if not isinstance(ranked, VoyagerSkillRankResult):
            raise TypeError(
                "Voyager retrieval port must return VoyagerSkillRankResult"
            )
        if len(ranked.names) > limit:
            raise ValueError("Voyager retrieval port exceeded top-k limit")
        by_name = {row.name: row for row in skills}
        unknown = tuple(name for name in ranked.names if name not in by_name)
        if unknown:
            raise ValueError(
                f"Voyager retrieval returned unknown skills: {unknown}"
            )
        selected = tuple(by_name[name] for name in ranked.names)
        result = {
            "query": query,
            "program_names": ranked.names,
            "program_codes": tuple(row.code for row in selected),
            "skill_digests": tuple(row.skill_digest for row in selected),
            "scores": ranked.scores,
            "retrieval_receipt": thaw_json(ranked.receipt),
            "retrieval_digest": ranked.result_digest,
        }
        return ProgramNodeResult(
            value=result,
            state_update={"result": result},
            events=({
                "type": "voyager_skills_retrieved",
                "query_digest": canonical_digest(query),
                "program_names": ranked.names,
                "skill_digests": result["skill_digests"],
                "retrieval_digest": ranked.result_digest,
            },),
        )

    raise ValueError(f"unsupported Voyager skill-memory event: {kind}")


def build_voyager_skill_memory_program() -> ResearchProgram:
    return (
        MemoryProgramBuilder.create(
            program_id="voyager.skill-memory",
            version=VOYAGER_AUDITED_COMMIT[:12],
            state_schema="voyager.skill-memory.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "voyager.skill-memory.dispatch",
            configuration={
                "memory_concerns": (
                    MemoryConcern.WRITE.value,
                    MemoryConcern.RETRIEVAL.value,
                    MemoryConcern.INDEX.value,
                ),
                "source_commit": VOYAGER_AUDITED_COMMIT,
            },
            next_node="dispatch",
        )
        .build()
    )


VOYAGER_SKILL_MEMORY_PROGRAM = build_voyager_skill_memory_program()


def voyager_skill_memory_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "voyager.skill-memory.dispatch",
            _dispatch,
            canonical_digest({
                "operation": "voyager.skill-memory.dispatch",
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "implementation_revision": 2,
            }),
        ),
    )


def voyager_skill_memory_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="voyager.skill-memory",
        program=VOYAGER_SKILL_MEMORY_PROGRAM,
        operations=voyager_skill_memory_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=4,
        dependency_identity={
            "source_commit": VOYAGER_AUDITED_COMMIT,
            "skill_retrieval_top_k": (
                VOYAGER_MINECRAFT_FIDELITY.skill_retrieval_top_k
            ),
        },
    )


__all__ = [
    "VOYAGER_SKILL_MEMORY_PROGRAM",
    "VoyagerSkill",
    "VoyagerSkillDescriptionPort",
    "VoyagerSkillDescriptionRequest",
    "VoyagerSkillMemoryBinding",
    "VoyagerSkillRankRequest",
    "VoyagerSkillRankResult",
    "VoyagerSkillRetrieverPort",
    "build_voyager_skill_memory_program",
    "voyager_skill_memory_host",
    "voyager_skill_memory_initial_data",
    "voyager_skill_memory_operations",
]
