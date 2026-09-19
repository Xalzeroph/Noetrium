from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildResearchHostRegistry,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition import (
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)
from research.reproductions.worldmm_memory.memory import (
    WORLDMM_MEMORY_PROGRAM,
    WorldMMEvidenceItem,
    WorldMMFacetIndexResult,
    WorldMMFacetRetrieveResult,
    WorldMMMemoryBinding,
    WorldMMMemoryType,
    worldmm_memory_host,
)
from research.reproductions.worldmm_memory.program import (
    WORLDMM_METHOD_PROGRAM,
    worldmm_method_initial_state,
)


class _Facet:
    def __init__(self, memory_type: WorldMMMemoryType) -> None:
        self._memory_type = memory_type
        self.retrieve_calls = []

    @property
    def memory_type(self) -> WorldMMMemoryType:
        return self._memory_type

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "worldmm-facet",
            "memory_type": self.memory_type.value,
            "implementation_revision": 1,
        })

    def index(self, request):
        return WorldMMFacetIndexResult(
            self.memory_type,
            request.until_time,
            {
                WorldMMMemoryType.EPISODIC: 40,
                WorldMMMemoryType.SEMANTIC: 17,
                WorldMMMemoryType.VISUAL: 12,
            }[self.memory_type],
            {"fixture": self.memory_type.value},
        )

    def retrieve(self, request):
        self.retrieve_calls.append(request)
        if self.memory_type is WorldMMMemoryType.EPISODIC:
            assert request.top_k == 3
            assert request.configuration["granularities"] == (
                "30sec",
                "3min",
                "10min",
                "1h",
            )
            assert request.excluded_item_ids == ()
            items = (
                WorldMMEvidenceItem(
                    "shared-event",
                    self.memory_type,
                    "[DAY1 10:00:00 - DAY1 10:00:30]\nAlex carried a blue bag.",
                ),
            )
        elif self.memory_type is WorldMMMemoryType.SEMANTIC:
            assert request.top_k == 10
            assert request.configuration["ppr_damping"] == 0.85
            assert "shared-event" in request.excluded_item_ids
            items = (
                WorldMMEvidenceItem(
                    "semantic_110100000_0",
                    self.memory_type,
                    "(Alex, owns, blue bag)",
                ),
            )
        else:
            assert request.top_k == 3
            items = (
                WorldMMEvidenceItem(
                    "DAY1 10:00:00 - DAY1 10:00:30",
                    self.memory_type,
                    artifact_refs=(
                        "sha256:" + canonical_digest({"frame": 1}),
                    ),
                ),
            )
        return WorldMMFacetRetrieveResult(
            self.memory_type,
            request.query,
            items,
            {"fixture": self.memory_type.value},
        )


def _children(journal):
    episodic = _Facet(WorldMMMemoryType.EPISODIC)
    semantic = _Facet(WorldMMMemoryType.SEMANTIC)
    visual = _Facet(WorldMMMemoryType.VISUAL)
    binding = WorldMMMemoryBinding(
        episodic=episodic,
        semantic=semantic,
        visual=visual,
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(
        worldmm_memory_host(journal=journal),
        binding,
    )
    return (
        registry.executor(),
        episodic,
        semantic,
        visual,
    )


class _Capabilities:
    def __init__(
        self,
        reasoning_responses,
        answer="B",
    ) -> None:
        self.reasoning_responses = list(reasoning_responses)
        self.answer = answer
        self.requests = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            EffectClass.PURE,
            False,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        if request.capability_id == "worldmm.reasoning.generate":
            value = self.reasoning_responses.pop(0)
        elif request.capability_id == "worldmm.answer.generate":
            value = self.answer
        else:
            raise KeyError(request.capability_id)
        return CapabilityResult(
            request.capability_id,
            value,
        )


def test_worldmm_runs_adaptive_cross_facet_memory_as_nested_machine() -> None:
    child_journal = InMemoryMachineJournal()
    children, episodic, semantic, visual = _children(child_journal)
    capabilities = _Capabilities((
        (
            '{"decision":"search","selected_memory":'
            '{"memory_type":"episodic","search_query":"Alex blue bag"}}'
        ),
        (
            '{"decision":"search","selected_memory":'
            '{"memory_type":"semantic","search_query":"Alex bag ownership"}}'
        ),
        '{"decision":"answer"}',
    ))
    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            "worldmm-run",
            "trace",
            "span",
            study_id="worldmm",
            task_id="egolifeqa:test",
        ),
        capabilities=capabilities,
        child_machines=children,
        runtime_binding_digest=canonical_digest({
            "fixture": "worldmm-method-runtime",
            "capability_surface": (
                "worldmm.reasoning.generate",
                "worldmm.answer.generate",
            ),
        }),
    )
    runtime = bind_machine_method_runtime(
        WORLDMM_METHOD_PROGRAM,
        runtime,
        machine_id="method:worldmm:test",
    )
    result = UniversalMethodMachine(max_steps=64).run(
        WORLDMM_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=worldmm_method_initial_state(
            question="Who owns the blue bag?",
            choices={
                "A": "Maria",
                "B": "Alex",
                "C": "Luis",
                "D": "Sam",
            },
            until_time=110300000,
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["answer"] == "B"
    assert result.value["round_count"] == 3
    assert result.value["error_count"] == 0
    assert len(result.value["round_history"]) == 2
    assert tuple(
        row["memory_type"]
        for row in result.value["round_history"]
    ) == ("episodic", "semantic")
    assert len(result.value["retrieved_items"]) == 2
    assert len(episodic.retrieve_calls) == 1
    assert len(semantic.retrieve_calls) == 1
    assert len(visual.retrieve_calls) == 0

    memory_machine_id = "method:worldmm:test:worldmm-memory"
    memory_commits = child_journal.commits(memory_machine_id)
    assert memory_commits
    assert any(
        commit.program_digest == WORLDMM_MEMORY_PROGRAM.program_digest
        for commit in memory_commits
    )
    assert runtime.transitions is not None
    parent_commits = runtime.transitions.machine.journal.commits(
        "method:worldmm:test"
    )
    links = tuple(
        link
        for commit in parent_commits
        for link in commit.child_links
    )
    assert any(
        link.child_machine_id == memory_machine_id
        for link in links
    )


def test_worldmm_malformed_reasoning_json_defaults_to_final_answer() -> None:
    child_journal = InMemoryMachineJournal()
    children, episodic, semantic, visual = _children(child_journal)
    capabilities = _Capabilities(("not valid json",), answer="A")
    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            "worldmm-malformed",
            "trace",
            "span",
            task_id="egolifeqa:malformed",
        ),
        capabilities=capabilities,
        child_machines=children,
        runtime_binding_digest=canonical_digest({
            "fixture": "worldmm-malformed-runtime",
        }),
    )
    runtime = bind_machine_method_runtime(
        WORLDMM_METHOD_PROGRAM,
        runtime,
        machine_id="method:worldmm:malformed",
    )
    result = UniversalMethodMachine(max_steps=32).run(
        WORLDMM_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=worldmm_method_initial_state(
            question="What happened?",
            choices={"A": "A", "B": "B"},
            until_time=110300000,
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["answer"] == "A"
    assert result.value["round_count"] == 1
    assert result.value["round_history"] == ()
    assert episodic.retrieve_calls == []
    assert semantic.retrieve_calls == []
    assert visual.retrieve_calls == []
