from __future__ import annotations

from noetrium.platform import run_method_program
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from research.benchmarks.multiagentbench import (
    MultiAgentBenchTaskRecord,
    build_multiagentbench_task_set,
)
from research.reproductions.autogen_agentchat.program import (
    autogen_groupchat_initial_state,
    build_autogen_groupchat_method_program,
)
from research.reproductions.autogen_agentchat.study import (
    build_autogen_multiagentbench_study,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="autogen-run",
        trace_id="trace-1",
        span_id="span-1",
        study_id="autogen-multiagentbench",
        task_id="research-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _GroupChatAgents:
    def __init__(self) -> None:
        self.manager_outputs = [
            {"speaker": "ghost"},
            {"speaker": "agent2"},
            {"speaker": "user_proxy"},
        ]
        self.participant_outputs = {
            "agent1": [
                {"content": "Agent 1 contributes evidence."},
            ],
            "agent2": [
                {
                    "content": "Agent 2 requests administrator review.",
                    "admin_interrupt": True,
                },
            ],
            "user_proxy": [
                {
                    "content": "Administrator approves the result.",
                    "terminate": True,
                },
            ],
        }
        self.calls: list[str] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append(request.agent_id)
        if request.agent_id == "autogen.group-manager":
            if not self.manager_outputs:
                raise AssertionError("manager output sequence exhausted")
            return MethodAgentResult(value=self.manager_outputs.pop(0))
        outputs = self.participant_outputs.get(request.agent_id)
        if not outputs:
            raise AssertionError(f"participant output exhausted: {request.agent_id}")
        return MethodAgentResult(value=outputs.pop(0))


def test_autogen_groupchat_dynamic_speaker_fallback_interrupt_and_resume(tmp_path) -> None:
    participants = ("agent1", "agent2", "user_proxy")
    program = build_autogen_groupchat_method_program(participants)
    agents = _GroupChatAgents()
    state_root = tmp_path / "machine"

    first = run_method_program(
        program,
        runtime=MethodRuntimeContext(_context(), agent_loop=agents),
        initial_state=autogen_groupchat_initial_state(
            participant_ids=participants,
            task_instruction="Collaboratively produce one final answer.",
        ),
        state_root=state_root,
    )

    assert first.status is MethodRunStatus.INTERRUPTED
    assert first.state["round"] == 2
    assert first.state["speaker_fallback_count"] == 1
    assert first.state["interrupt_count"] == 1
    assert tuple(row["speaker"] for row in first.state["transcript"]) == (
        "agent1",
        "agent2",
    )
    assert first.state["transcript"][0]["recipients"] == (
        "agent2",
        "user_proxy",
    )
    assert first.state["transcript"][1]["recipients"] == (
        "agent1",
        "user_proxy",
    )

    resumed = run_method_program(
        program,
        runtime=MethodRuntimeContext(_context(), agent_loop=agents),
        resume=True,
        state_root=state_root,
    )

    assert resumed.status is MethodRunStatus.SUCCEEDED
    assert resumed.value["terminated"] is True
    assert resumed.value["round_count"] == 3
    assert resumed.value["message_count"] == 3
    assert resumed.value["speaker_fallback_count"] == 1
    assert resumed.value["interrupt_count"] == 1
    assert tuple(row["speaker"] for row in resumed.value["transcript"]) == (
        "agent1",
        "agent2",
        "user_proxy",
    )
    assert resumed.value["transcript"][2]["recipients"] == ("agent1", "agent2")
    assert agents.calls == [
        "autogen.group-manager",
        "agent1",
        "autogen.group-manager",
        "agent2",
        "autogen.group-manager",
        "user_proxy",
    ]


def test_autogen_multiagentbench_study_freezes_team_and_metrics() -> None:
    participants = ("agent1", "agent2", "user_proxy")
    benchmark = build_multiagentbench_task_set(
        (
            MultiAgentBenchTaskRecord(
                task_id="research-1",
                environment="research",
                split_id="test",
                participant_roles=participants,
                content_digest="c" * 64,
            ),
        ),
        harness_commit="a" * 40,
        task_manifest_revision="task-cut-1",
        source_content_sha256="b" * 64,
    )

    study = build_autogen_multiagentbench_study(
        benchmark,
        split_id="test",
        participant_ids=participants,
    )

    roles = tuple(row.role for row in study.binding_requirements.participants)
    assert roles == ("agent1", "agent2", "manager", "user_proxy")
    assert study.benchmark.cut_digest == benchmark.cut_digest
    assert tuple(
        row.measurement_id for row in study.measurement_protocol.definitions
    ) == (
        "interrupt_count",
        "message_count",
        "round_count",
        "speaker_fallback_count",
        "task_success",
    )
    assert (
        study.trial_protocol_identity.protocol_id
        == "autogen.paper-era.multiagentbench.v1"
    )
