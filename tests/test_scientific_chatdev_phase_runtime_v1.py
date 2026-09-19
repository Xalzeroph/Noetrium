from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    InMemoryMachineJournal,
    MachineStatus,
    canonical_digest,
)
from research.reproductions.chatdev_v1.chain import CHATDEV_V1_SIMPLE_PHASES
from research.reproductions.chatdev_v1.runtime import (
    ChatDevV1PhaseRuntimeBinding,
    ChatDevV1RolePlayExchange,
    chatdev_v1_phase_initial_data,
    chatdev_v1_phase_runtime_host,
)


class _ScriptedRolePlay:
    def __init__(self, exchanges):
        self.exchanges = list(exchanges)
        self.requests = []

    @property
    def identity_digest(self):
        return canonical_digest({
            "provider": "chatdev-test-roleplay",
            "script": tuple(
                exchange.exchange_digest
                for exchange in self.exchanges
            ),
        })

    def exchange(self, request):
        self.requests.append(request)
        if not self.exchanges:
            raise AssertionError("unexpected ChatDev role-play exchange")
        return self.exchanges.pop(0)


def _binding(role_play):
    return ChatDevV1PhaseRuntimeBinding(
        role_play=role_play,
        role_prompts={
            "Chief Product Officer": "product role",
            "Chief Executive Officer": "ceo role",
            "Chief Technology Officer": "cto role",
            "Programmer": "programmer role",
            "Counselor": "counselor role",
        },
    )


def test_chatdev_reflection_is_an_explicit_runtime_node_after_terminated_chat() -> None:
    role_play = _ScriptedRolePlay([
        ChatDevV1RolePlayExchange(
            assistant_message="The discussion did not mark a conclusion.",
            user_message="Agreed.",
            assistant_terminated=True,
        ),
        ChatDevV1RolePlayExchange(
            assistant_message="PowerPoint",
            user_message="PowerPoint",
        ),
    ])
    binding = _binding(role_play)
    journal = InMemoryMachineJournal()
    host = chatdev_v1_phase_runtime_host(journal=journal)
    execution = host.execute(
        machine_id="runtime:chatdev:demand-analysis",
        instance_identity={
            "phase": "DemandAnalysis",
            "binding_digest": binding.binding_digest,
        },
        binding=binding,
        initial_data=chatdev_v1_phase_initial_data(
            phase=CHATDEV_V1_SIMPLE_PHASES["DemandAnalysis"],
            task_prompt="Build a slide authoring tool.",
            phase_prompt="Decide the product modality.",
        ),
        command_id_prefix="chatdev:demand-analysis",
    )

    assert execution.status is MachineStatus.COMPLETED
    assert execution.previous_value["phase_name"] == "DemandAnalysis"
    assert execution.previous_value["turn_count"] == 1
    assert execution.previous_value["reflected"] is True
    assert execution.previous_value["conclusion"] == "PowerPoint"
    assert len(role_play.requests) == 2
    assert role_play.requests[0].reflection is False
    assert role_play.requests[1].reflection is True
    assert role_play.requests[1].assistant_role == "Chief Executive Officer"
    assert role_play.requests[1].user_role == "Counselor"
    # open/start + exchange + reflection + finalize
    assert len(journal.commits(execution.machine_id)) == 4


def test_chatdev_non_reflection_phase_preserves_v1_assistant_overwrite_semantics() -> None:
    role_play = _ScriptedRolePlay([
        ChatDevV1RolePlayExchange(
            assistant_message="assistant-final-code",
            user_message="<INFO> user-side-conclusion",
            user_info=True,
        ),
    ])
    binding = _binding(role_play)
    journal = InMemoryMachineJournal()
    host = chatdev_v1_phase_runtime_host(journal=journal)
    execution = host.execute(
        machine_id="runtime:chatdev:coding",
        instance_identity={
            "phase": "Coding",
            "binding_digest": binding.binding_digest,
        },
        binding=binding,
        initial_data=chatdev_v1_phase_initial_data(
            phase=CHATDEV_V1_SIMPLE_PHASES["Coding"],
            task_prompt="Build a calculator.",
            phase_prompt="Write the implementation.",
        ),
        command_id_prefix="chatdev:coding",
    )

    assert execution.status is MachineStatus.COMPLETED
    # ChatDev v1.0.0 Phase.chatting overwrites seminar_conclusion with
    # assistant_response.msg.content whenever need_reflect is false.
    assert execution.previous_value["conclusion"] == "assistant-final-code"
    assert execution.previous_value["stop_reason"] == "user_info"
    assert execution.previous_value["reflected"] is False
    assert execution.previous_value["turn_count"] == 1
    # open/start + exchange + finalize
    assert len(journal.commits(execution.machine_id)) == 3
