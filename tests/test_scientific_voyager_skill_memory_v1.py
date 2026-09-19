from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.voyager_minecraft.skill_memory import (
    VOYAGER_SKILL_MEMORY_PROGRAM,
    VoyagerSkillDescriptionRequest,
    VoyagerSkillMemoryBinding,
    VoyagerSkillRankRequest,
    VoyagerSkillRankResult,
    voyager_skill_memory_host,
    voyager_skill_memory_initial_data,
)


class _Descriptions:
    def __init__(self, revision: int = 1) -> None:
        self._revision = revision

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "description_generator": "fixture",
            "revision": self._revision,
        })

    def describe(self, request: VoyagerSkillDescriptionRequest) -> str:
        return (
            f"async function {request.program_name}(bot) "
            f"{{ // {request.program_code} }}"
        )


class _Retriever:
    def __init__(self, revision: int = 1) -> None:
        self._revision = revision

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "retriever": "fixture",
            "revision": self._revision,
        })

    def rank(self, request: VoyagerSkillRankRequest) -> VoyagerSkillRankResult:
        query = request.query.lower()
        ranked = sorted(
            request.skills,
            key=lambda skill: (
                0 if query in skill.description.lower() else 1,
                skill.name,
            ),
        )[: request.limit]
        return VoyagerSkillRankResult(
            names=tuple(skill.name for skill in ranked),
            scores=tuple(float(len(ranked) - index) for index, _ in enumerate(ranked)),
            receipt={
                "query": request.query,
                "limit": request.limit,
            },
        )


def _event(kind: str, payload: dict) -> dict:
    return {
        "event": {
            "kind": kind,
            "payload": payload,
            "source": "test",
        }
    }


def test_voyager_skill_memory_is_one_persistent_journal_backed_machine() -> None:
    journal = InMemoryMachineJournal()
    binding = VoyagerSkillMemoryBinding(_Descriptions(), _Retriever())
    host = voyager_skill_memory_host(journal=journal)
    machine_id = "memory:voyager-skills:test"
    identity = {
        "memory_id": "voyager-skills:test",
        "program_digest": VOYAGER_SKILL_MEMORY_PROGRAM.program_digest,
        "binding_digest": binding.binding_digest,
    }
    initial = voyager_skill_memory_initial_data()

    first = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.skill.write",
            {
                "program_name": "mineWood",
                "program_code": "await mineBlock(bot, 'oak_log', 1);",
            },
        ),
        command_id_prefix="voyager-skill:test",
    )
    assert first.status is MachineStatus.RUNNABLE
    assert first.data["sequence"] == 1
    assert len(first.data["active_skills"]) == 1
    first_digest = first.previous_value["skill_digest"]

    second = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.skill.write",
            {
                "program_name": "mineWood",
                "program_code": "await mineBlock(bot, 'birch_log', 1);",
            },
        ),
        command_id_prefix="voyager-skill:test",
    )
    assert second.status is MachineStatus.RUNNABLE
    assert second.data["sequence"] == 2
    assert len(second.data["active_skills"]) == 1
    assert len(second.data["skill_history"]) == 2
    assert second.previous_value["revision"] == 2
    assert second.previous_value["supersedes_digest"] == first_digest

    third = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.skill.write",
            {
                "program_name": "craftTable",
                "program_code": "await craftItem(bot, 'crafting_table', 1);",
            },
        ),
        command_id_prefix="voyager-skill:test",
    )
    assert third.data["sequence"] == 3
    assert len(third.data["active_skills"]) == 2

    retrieved = host.step_once(
        machine_id=machine_id,
        instance_identity=identity,
        binding=binding,
        initial_data=initial,
        payload=_event(
            "voyager.skill.retrieve",
            {
                "query": "craftTable",
                "limit": 100,
            },
        ),
        command_id_prefix="voyager-skill:test",
    )
    assert retrieved.status is MachineStatus.RUNNABLE
    assert retrieved.previous_value["program_names"][0] == "craftTable"
    assert len(retrieved.previous_value["program_names"]) <= 5
    assert retrieved.revision > third.revision
    assert len(journal.commits(machine_id)) == retrieved.revision


def test_voyager_skill_memory_binding_identity_tracks_retrieval_semantics() -> None:
    first = VoyagerSkillMemoryBinding(_Descriptions(1), _Retriever(1))
    second = VoyagerSkillMemoryBinding(_Descriptions(1), _Retriever(2))
    third = VoyagerSkillMemoryBinding(_Descriptions(2), _Retriever(1))

    assert first.binding_digest != second.binding_digest
    assert first.binding_digest != third.binding_digest
