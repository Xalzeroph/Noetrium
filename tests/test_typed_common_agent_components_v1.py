from __future__ import annotations

from components.reference.single_agent.agent import (
    ReferenceAgentAction,
    ReferenceAgentActionKind,
    ReferenceAgentDecision,
    ReferenceAgentMessage,
    ReferenceAgentRunResult,
    ReferenceAgentState,
    ReferenceAgentStatus,
    PlatformCapabilityToolPort,
    ReferencePlanAndSolveMethod,
    ReferenceReActMethod,
    ReferenceToolRegistryPort,
    JsonlReferenceAgentProgress,
)
from components.reference.single_agent.memory import MemoryItem, VectorMemoryStore, WorkingMemory
from orchestration.multi_agent import (
    CommunicationEdge,
    CommunicationTopology,
    MultiAgentMessage,
    MultiAgentRunStatus,
    MultiAgentRuntime,
    group_chat_initial_messages,
)
from components.reference.single_agent.tools import (
    ToolArguments,
    ToolAuthorization,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    ToolRiskClass,
)


class _Policy:
    def decide(self, state):
        if state.step == 0:
            return ReferenceAgentDecision(
                ReferenceAgentAction(
                    ReferenceAgentActionKind.TOOL,
                    "echo",
                    {"value": "observed"},
                    "use echo",
                )
            )
        return ReferenceAgentDecision(ReferenceAgentAction(ReferenceAgentActionKind.FINAL, "answer", content="done"))


def test_react_is_importable_and_tool_registry_is_explicit() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("echo", "return text", "tool.echo.v1"),
        lambda arguments: ToolResult("echo", True, arguments.as_mapping()["value"]),
    )
    result = ReferenceReActMethod(_Policy(), ReferenceToolRegistryPort(registry)).run("task", max_steps=3)
    assert result.status is ReferenceAgentStatus.COMPLETED
    assert result.answer == "done"
    assert registry.definitions()[0].name == "echo"


def test_working_and_vector_memory_are_bounded_and_deterministic() -> None:
    working = WorkingMemory(capacity=2)
    working.remember(MemoryItem("a", "first", embedding=(1.0, 0.0)))
    working.remember(MemoryItem("b", "second", embedding=(0.0, 1.0)))
    working.remember(MemoryItem("c", "third", embedding=(1.0, 1.0)))
    assert tuple(item.memory_id for item in working.items()) == ("b", "c")
    vector = VectorMemoryStore(dimension=2)
    vector.upsert(MemoryItem("x", "x", embedding=(1.0, 0.0)))
    vector.upsert(MemoryItem("y", "y", embedding=(0.0, 1.0)))
    assert vector.search((1.0, 0.0), limit=1)[0][0].memory_id == "x"


class _Node:
    def __init__(self, name: str) -> None:
        self.name = name

    def handle(self, message: MultiAgentMessage) -> tuple[MultiAgentMessage, ...]:
        if message.turn >= 2:
            return ()
        target = "worker" if self.name == "manager" else "manager"
        return (MultiAgentMessage(
            self.name,
            target,
            f"reply:{message.content}",
            message.turn + 1,
            causal_parent_ids=(message.message_id,),
        ),)



def test_multi_agent_layer_delivers_only_over_declared_topology() -> None:
    topology = CommunicationTopology(
        ("manager", "worker"),
        (
            CommunicationEdge("manager", "worker"),
            CommunicationEdge("worker", "manager"),
        ),
    )
    runtime = MultiAgentRuntime(
        topology,
        {"manager": _Node("manager"), "worker": _Node("worker")},
    )
    result = runtime.run(
        MultiAgentMessage("manager", "worker", "task", 0),
        max_rounds=4,
    )
    assert result.topology_digest == topology.topology_digest
    assert result.terminated is True
    assert [message.recipient for message in result.messages] == [
        "worker",
        "manager",
        "worker",
    ]

def test_component_stress_retrieval_and_tool_calls_remain_bounded() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from time import perf_counter
    from components.reference.single_agent.memory import EpisodicMemoryStore

    started = perf_counter()
    episodes = EpisodicMemoryStore()
    for index in range(4096):
        episodes.put(MemoryItem(f"episode-{index:05d}", f"trajectory-{index}", ("agent",)))
    assert len(episodes.search("trajectory-", limit=4096)) == 4096
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("identity", "return value", "tool.identity.v1"),
        lambda arguments: ToolResult("identity", True, arguments.as_mapping()["value"]),
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda index: registry.invoke(
                "identity",
                ToolArguments(
                    (("value", f"v-{index}"),)
                ),
            ),
            range(1024),
        ))
    assert all(result.success for result in results)
    assert perf_counter() - started < 20.0


def test_tool_capability_risk_is_default_deny_and_audited() -> None:
    definition = ToolDefinition(
        "write-file",
        "write a file",
        "tool.write.v1",
        capability_id="filesystem.write",
        risk_class=ToolRiskClass.HIGH_RISK,
        sandbox_profile="isolated",
    )
    calls = []
    denied = ToolRegistry()
    denied.register(definition, lambda _arguments: calls.append(True) or ToolResult("write-file", True, "done"))
    result = denied.invoke("write-file", ToolArguments.from_mapping({"path": "x"}))
    assert result.success is False
    assert "explicit authorization" in (result.error or "")
    assert calls == []

    audit_rows = []
    class Authorizer:
        def review(self, item, arguments):
            assert item is definition
            assert arguments.as_mapping()["path"] == "x"
            return ToolAuthorization("filesystem.write", True, "approved for test", "approval-1")

    class Audit:
        def record(self, item, arguments, item_result):
            audit_rows.append((item.definition_digest, arguments.digest, item_result.result_digest))

    allowed = ToolRegistry(authorization=Authorizer(), audit=Audit())
    allowed.register(definition, lambda _arguments: ToolResult("write-file", True, "done"))
    result = allowed.invoke("write-file", ToolArguments.from_mapping({"path": "x"}))
    assert result.success is True
    assert len(audit_rows) == 1


def test_memory_namespaces_isolate_same_ids_and_vector_results() -> None:
    from components.reference.single_agent.memory import EpisodicMemoryStore

    episodes = EpisodicMemoryStore()
    episodes.put(MemoryItem("same", "alpha", namespace="paper-a"))
    episodes.put(MemoryItem("same", "beta", namespace="paper-b"))
    assert episodes.get("same", namespace="paper-a").content == "alpha"
    assert episodes.get("same", namespace="paper-b").content == "beta"

    vectors = VectorMemoryStore(dimension=2)
    vectors.upsert(MemoryItem("same", "alpha", namespace="paper-a", embedding=(1.0, 0.0)))
    vectors.upsert(MemoryItem("same", "beta", namespace="paper-b", embedding=(0.0, 1.0)))
    assert tuple(
        row[0].namespace for row in vectors.search((0.0, 1.0), namespace="paper-b")
    ) == ("paper-b",)



def test_multi_agent_machine_cut_resume_preserves_transcript_and_retry_identity() -> None:
    topology = CommunicationTopology(
        ("manager", "worker"),
        (
            CommunicationEdge("manager", "worker"),
            CommunicationEdge("worker", "manager"),
        ),
    )
    runtime = MultiAgentRuntime(
        topology,
        {"manager": _Node("manager"), "worker": _Node("worker")},
    )
    initial = MultiAgentMessage("manager", "worker", "task", 0)
    retried = MultiAgentMessage(
        "manager",
        "worker",
        "task",
        0,
        delivery_attempt=1,
    )
    assert retried.message_id == initial.message_id

    paused = runtime.run(
        initial,
        max_rounds=4,
        max_messages=1,
    )
    assert paused.status is MultiAgentRunStatus.MAX_MESSAGES
    assert paused.machine_cut.revision > 0
    assert paused.messages == (initial,)
    assert tuple(message.turn for message in paused.pending_messages) == (1,)

    resumed = runtime.resume(
        "default",
        max_rounds=4,
        max_messages=10,
    )
    assert resumed.status is MultiAgentRunStatus.COMPLETED
    assert tuple(message.turn for message in resumed.messages) == (0, 1, 2)
    assert resumed.machine_cut.revision > paused.machine_cut.revision


def test_group_chat_broadcasts_to_every_declared_neighbor() -> None:
    class Leaf:
        def __init__(self):
            self.received = []

        def handle(self, message):
            self.received.append(message)
            return ()

    leaves = {"alpha": Leaf(), "beta": Leaf()}
    topology = CommunicationTopology(
        ("moderator", "alpha", "beta"),
        (
            CommunicationEdge("moderator", "alpha"),
            CommunicationEdge("moderator", "beta"),
        ),
    )
    runtime = MultiAgentRuntime(
        topology,
        {"moderator": Leaf(), **leaves},
    )
    result = runtime.run_many(
        group_chat_initial_messages(
            topology,
            "moderator",
            "topic",
        )
    )
    assert result.status is MultiAgentRunStatus.COMPLETED
    assert {message.recipient for message in result.messages} == {
        "alpha",
        "beta",
    }
    assert len(leaves["alpha"].received) == len(leaves["beta"].received) == 1


def test_multi_agent_cancellation_is_journaled_as_resumable_machine_wait() -> None:
    class Cancelled:
        def cancelled(self):
            return True

    topology = CommunicationTopology(
        ("manager", "worker"),
        (CommunicationEdge("manager", "worker"),),
    )
    initial = MultiAgentMessage("manager", "worker", "task", 0)
    result = MultiAgentRuntime(
        topology,
        {"manager": _Node("manager"), "worker": _Node("worker")},
    ).run(
        initial,
        cancellation=Cancelled(),
    )
    assert result.status is MultiAgentRunStatus.CANCELLED
    assert result.terminated is False
    assert result.pending_messages == (initial,)
    assert result.machine_cut.revision >= 2

def test_action_arguments_are_mapping_only_and_digest_stable() -> None:
    first = ReferenceAgentAction(
        ReferenceAgentActionKind.TOOL,
        "search",
        {"query": "agent", "limit": 3},
    )
    second = ReferenceAgentAction.from_mapping(
        ReferenceAgentActionKind.TOOL,
        "search",
        {"limit": 3, "query": "agent"},
    )
    assert first.arguments_mapping == {"query": "agent", "limit": 3}
    assert first.action_digest == second.action_digest


def test_plan_and_solve_emits_durable_lifecycle() -> None:
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from noetrium_platform.foundation.kernel.kernel import ExecutionContext

    class Planner:
        def plan(self, task):
            return ("inspect", f"answer {task}")

    class Solver:
        def solve(self, task, plan):
            return ReferenceAgentRunResult(
                ReferenceAgentStatus.COMPLETED,
                "done",
                ReferenceAgentState(
                    task,
                    messages=(ReferenceAgentMessage("solver", "done"),),
                    scratchpad=tuple(ReferenceAgentMessage("plan", step) for step in plan),
                    step=2,
                ),
            )

    with TemporaryDirectory() as directory:
        progress = JsonlReferenceAgentProgress(Path(directory) / "agent.jsonl")
        context = ExecutionContext("run-1", "trace-1", "span-1")
        result = ReferencePlanAndSolveMethod(
            Planner(), Solver(), progress=progress
        ).run("task", context=context)
        assert result.status is ReferenceAgentStatus.COMPLETED
        restored = progress.latest_state("run-1")
        assert restored is not None
        assert restored.task == "task"
        assert restored.step == 2


def test_graph_checkpoint_history_survives_restart_and_supports_time_travel() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from components.reference.graph import SQLiteGraphCheckpointer, StateGraph

    with TemporaryDirectory() as directory:
        path = Path(directory) / "graph.sqlite3"
        checkpointer = SQLiteGraphCheckpointer(path)
        try:
            graph = StateGraph()
            graph.add_node("increment", lambda state: {"count": state.get("count", 0) + 1})
            graph.set_entry_point("increment")
            compiled = graph.compile(checkpointer=checkpointer)
            compiled.invoke({"count": 0}, thread_id="thread-1")
            history = compiled.history("thread-1")
            assert len(history) == 2
            first = history[0]
        finally:
            checkpointer.close()

        reopened = SQLiteGraphCheckpointer(path)
        try:
            assert reopened.load_checkpoint(first.checkpoint_id) == first
            assert len(reopened.history("thread-1")) == 2
        finally:
            reopened.close()


def test_platform_capability_observation_keeps_typed_result() -> None:
    from noetrium_platform.capabilities.participant.capability.api import (
        CapabilityDescriptor,
        CapabilityResult,
    )
    from noetrium_platform.foundation.kernel.kernel import ExecutionContext

    class Capabilities:
        def describe(self, capability_id):
            return CapabilityDescriptor(capability_id, "v1", "request", "result")

        def invoke(self, request):
            return CapabilityResult(request.capability_id, {"ok": True})

    observation = PlatformCapabilityToolPort(
        Capabilities(), ExecutionContext("run", "trace", "span")
    ).invoke("echo", {"value": 1})
    assert isinstance(observation.capability_result, CapabilityResult)
    assert observation.result_digest == observation.capability_result.digest()
    assert observation.capability_id == "echo"



def test_multi_agent_directory_machine_journal_resumes_after_restart() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal

    topology = CommunicationTopology(
        ("manager", "worker"),
        (
            CommunicationEdge("manager", "worker"),
            CommunicationEdge("worker", "manager"),
        ),
    )
    initial = MultiAgentMessage("manager", "worker", "task", 0)
    with TemporaryDirectory() as directory:
        root = Path(directory) / "machine-journal"
        first = MultiAgentRuntime(
            topology,
            {"manager": _Node("manager"), "worker": _Node("worker")},
            journal=DirectoryMachineJournal(root),
        )
        paused = first.run(
            initial,
            max_rounds=4,
            max_messages=1,
        )
        assert paused.status is MultiAgentRunStatus.MAX_MESSAGES

        restarted = MultiAgentRuntime(
            topology,
            {"manager": _Node("manager"), "worker": _Node("worker")},
            journal=DirectoryMachineJournal(root),
        )
        inspected = restarted.inspect("default")
        assert inspected.machine_cut == paused.machine_cut
        assert inspected.pending_messages == paused.pending_messages

        resumed = restarted.resume(
            "default",
            max_rounds=4,
            max_messages=10,
        )
        assert resumed.status is MultiAgentRunStatus.COMPLETED
        assert resumed.machine_cut.revision > paused.machine_cut.revision

