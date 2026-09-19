from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildResearchHostRegistry,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition import (
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)
from research.reproductions.voyager_minecraft.chest_memory import (
    VOYAGER_CHEST_MEMORY_PROGRAM,
    voyager_chest_memory_host,
)
from research.reproductions.voyager_minecraft.curriculum_memory import (
    VoyagerQAMemoryBinding,
    VoyagerQANearestRequest,
    VoyagerQANearestResult,
    voyager_qa_memory_host,
)
from research.reproductions.voyager_minecraft.program import (
    VOYAGER_MINECRAFT_METHOD_PROGRAM,
    voyager_minecraft_initial_state,
)
from research.reproductions.voyager_minecraft.skill_memory import (
    VOYAGER_SKILL_MEMORY_PROGRAM,
    VoyagerSkillDescriptionRequest,
    VoyagerSkillMemoryBinding,
    VoyagerSkillRankRequest,
    VoyagerSkillRankResult,
    voyager_skill_memory_host,
)


class _Descriptions:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "voyager-description",
            "implementation_revision": 1,
        })

    def describe(self, request: VoyagerSkillDescriptionRequest) -> str:
        return f"async function {request.program_name}(bot) {{ // learned skill }}"


class _Retriever:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "voyager-retriever",
            "implementation_revision": 1,
        })

    def rank(self, request: VoyagerSkillRankRequest) -> VoyagerSkillRankResult:
        selected = request.skills[: request.limit]
        return VoyagerSkillRankResult(
            names=tuple(skill.name for skill in selected),
            scores=tuple(
                float(len(selected) - index)
                for index, _ in enumerate(selected)
            ),
            receipt={"query": request.query},
        )


class _Agents:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append(request.agent_id)
        if request.agent_id == "voyager.action":
            assert request.view["task"] == "Mine 1 wood log"
            assert request.view["attempt"] == 0
            assert request.view["retrieved_skill_codes"] == ()
            return MethodAgentResult(
                value={
                    "program_name": "mineWood",
                    "program_code": (
                        "async function mineWood(bot) { "
                        "await mineBlock(bot, 'oak_log', 1); }"
                    ),
                    "exec_code": "await mineWood(bot);",
                }
            )
        if request.agent_id == "voyager.critic":
            assert request.view["task"] == "Mine 1 wood log"
            assert "Chests:" in request.view["chest_observation"]
            return MethodAgentResult(
                value={"success": True, "critique": ""}
            )
        raise AssertionError(
            f"unexpected Voyager agent call: {request.agent_id}"
        )


class _MinecraftProgramCapability:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "execution.program.execute",
            "1",
            "noetrium.program-execution-capability.request.v1",
            "noetrium.program-execution-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )
        self._random_descriptor = CapabilityDescriptor(
            "research.random.bernoulli-mask",
            "1",
            "research.random.bernoulli-mask.request.v1",
            "research.random.bernoulli-mask.result.v1",
            effect_class=EffectClass.PURE,
        )

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id == "execution.program.execute":
            return self._descriptor
        if capability_id == "research.random.bernoulli-mask":
            return self._random_descriptor
        raise AssertionError(f"unexpected capability: {capability_id}")

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        if request.capability_id == "research.random.bernoulli-mask":
            return CapabilityResult(
                capability_id=request.capability_id,
                payload={
                    "included_items": tuple(request.payload["items"]),
                    "receipt": {
                        "fixture": "include-all",
                        "probability": request.payload["probability"],
                    },
                },
                generation="random:test:1",
                request_digest=capability_request_digest(request),
            )
        assert request.capability_id == "execution.program.execute"
        assert request.payload["language"] == "javascript"
        assert request.payload["entrypoint"] in ("mineWood", "mineStone")
        assert request.payload["program_id"] in (
            "voyager.skill.mineWood",
            "voyager.skill.mineStone",
        )
        assert request.payload["parent_program_digests"] == ()
        assert request.payload["entrypoint"] in request.payload["source_text"]
        assert request.payload["invocation"]["expression"] in (
            "await mineWood(bot);",
            "await mineStone(bot);",
        )
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id=request.capability_id,
            payload={
                "status": "succeeded",
                "result": {
                    "observation": {
                        "status": {
                            "inventoryUsed": 1,
                            "biome": "forest",
                            "health": 20,
                            "food": 20,
                        },
                        "inventory": {"oak_log": 1},
                    },
                    "nearby_chests": {
                        "(1, 64, 1)": {"stick": 2},
                    },
                    "chat_summary": "",
                    "execution_errors": (),
                },
            },
            generation="minecraft:test:1",
            effect=EffectReceipt(
                effect_id="voyager-minecraft-effect-1",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_voyager_method_runs_one_successful_task_and_preserves_release_iteration_boundary() -> None:
    child_journal = InMemoryMachineJournal()
    skill_binding = VoyagerSkillMemoryBinding(
        _Descriptions(),
        _Retriever(),
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(
        voyager_skill_memory_host(journal=child_journal),
        skill_binding,
    )
    registry.register_static(
        voyager_chest_memory_host(journal=child_journal),
    )
    children = registry.executor()
    agents = _Agents()
    minecraft = _MinecraftProgramCapability()

    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            "voyager-run",
            "trace",
            "span",
            study_id="voyager",
            task_id="minecraft:lifelong",
        ),
        capabilities=minecraft,
        agent_loop=agents,
        child_machines=children,
    )
    runtime = bind_machine_method_runtime(
        VOYAGER_MINECRAFT_METHOD_PROGRAM,
        runtime,
        machine_id="method:voyager:test",
    )
    initial = voyager_minecraft_initial_state(
        initial_observation={
            "status": {"inventoryUsed": 0, "biome": "forest"},
        }
    )
    # The paper release checks iteration > 160 only before starting the next
    # task, so an attempt begun at 160 is allowed to push the recorder to 161.
    initial["action_iteration"] = 160

    result = UniversalMethodMachine(max_steps=64).run(
        VOYAGER_MINECRAFT_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial,
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["action_iteration"] == 161
    assert result.value["completed_tasks"] == ("Mine 1 wood log",)
    assert result.value["failed_tasks"] == ()
    assert result.value["learned_skill_count"] == 1
    assert agents.calls == ["voyager.action", "voyager.critic"]
    assert len(minecraft.requests) == 1

    skill_machine_id = "method:voyager:test:voyager-skill-memory"
    chest_machine_id = "method:voyager:test:voyager-chest-memory"
    skill_commits = child_journal.commits(skill_machine_id)
    chest_commits = child_journal.commits(chest_machine_id)
    assert skill_commits
    assert chest_commits
    assert skill_commits[-1].program_digest == (
        VOYAGER_SKILL_MEMORY_PROGRAM.program_digest
    )
    assert chest_commits[-1].program_digest == (
        VOYAGER_CHEST_MEMORY_PROGRAM.program_digest
    )

    assert runtime.transitions is not None
    parent_commits = runtime.transitions.machine.journal.commits(
        "method:voyager:test"
    )
    links = tuple(
        link
        for commit in parent_commits
        for link in commit.child_links
    )
    assert any(
        link.child_machine_id == skill_machine_id
        for link in links
    )
    assert any(
        link.child_machine_id == chest_machine_id
        for link in links
    )



class _NoReuseNearest:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "voyager-qa-no-reuse",
            "implementation_revision": 1,
        })

    def nearest(
        self,
        request: VoyagerQANearestRequest,
    ) -> VoyagerQANearestResult:
        if not request.cached_questions:
            return VoyagerQANearestResult(None, None)
        return VoyagerQANearestResult(
            question=request.cached_questions[0],
            distance=1.0,
            receipt={"query": request.question},
        )


class _CurriculumAgents:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.qa_questions: list[str] = []
        self.curriculum_message = ""

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append(request.agent_id)
        if request.agent_id == "voyager.curriculum_qa_questions":
            assert "Biome: forest" in request.view["observation"]
            return MethodAgentResult(
                value=(
                    "Reasoning: gather local knowledge\n"
                    "Question 1: How to craft a torch?\n"
                    "Concept 1: torch\n"
                    "Question 2: How to smelt raw iron?\n"
                    "Concept 2: furnace\n"
                )
            )
        if request.agent_id == "voyager.curriculum_qa":
            question = request.view["question"]
            self.qa_questions.append(question)
            return MethodAgentResult(
                value=f"Answer: knowledge for {question}"
            )
        if request.agent_id == "voyager.curriculum":
            self.curriculum_message = request.view["human_message"]
            assert "Question 1:" in self.curriculum_message
            assert "Biome: forest" in self.curriculum_message
            return MethodAgentResult(
                value={"task": "Mine 1 stone"}
            )
        if request.agent_id == "voyager.action":
            assert request.view["task"] == "Mine 1 stone"
            return MethodAgentResult(
                value={
                    "program_name": "mineStone",
                    "program_code": (
                        "async function mineStone(bot) { "
                        "await mineBlock(bot, 'stone', 1); }"
                    ),
                    "exec_code": "await mineStone(bot);",
                }
            )
        if request.agent_id == "voyager.critic":
            assert request.view["task"] == "Mine 1 stone"
            return MethodAgentResult(
                value={"success": True, "critique": ""}
            )
        raise AssertionError(
            f"unexpected Voyager agent call: {request.agent_id}"
        )


def test_voyager_curriculum_run_qa_enrichment_is_memory_backed_and_randomness_is_receipted() -> None:
    child_journal = InMemoryMachineJournal()
    skill_binding = VoyagerSkillMemoryBinding(
        _Descriptions(),
        _Retriever(),
    )
    qa_binding = VoyagerQAMemoryBinding(_NoReuseNearest())
    registry = ChildResearchHostRegistry()
    registry.register_static(
        voyager_skill_memory_host(journal=child_journal),
        skill_binding,
    )
    registry.register_static(
        voyager_chest_memory_host(journal=child_journal),
    )
    registry.register_static(
        voyager_qa_memory_host(journal=child_journal),
        qa_binding,
    )
    children = registry.executor()
    agents = _CurriculumAgents()
    capabilities = _MinecraftProgramCapability()

    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            "voyager-curriculum-run",
            "trace",
            "span",
            study_id="voyager",
            task_id="minecraft:curriculum",
        ),
        capabilities=capabilities,
        agent_loop=agents,
        child_machines=children,
    )
    runtime = bind_machine_method_runtime(
        VOYAGER_MINECRAFT_METHOD_PROGRAM,
        runtime,
        machine_id="method:voyager:curriculum",
    )
    initial = voyager_minecraft_initial_state(
        initial_observation={
            "status": {
                "inventoryUsed": 4,
                "biome": "forest",
                "timeOfDay": "day",
                "entities": {"cow": 3.0},
                "health": 20,
                "food": 20,
                "position": {"x": 0, "y": 64, "z": 0},
                "equipment": (),
            },
            "voxels": ("oak_log", "grass_block"),
            "blockRecords": ("oak_log", "grass_block", "stone"),
            "inventory": {"oak_log": 1, "stick": 2},
        }
    )
    initial["completed_tasks"] = tuple(
        f"completed-{index}" for index in range(15)
    )
    initial["action_iteration"] = 160

    result = UniversalMethodMachine(max_steps=256).run(
        VOYAGER_MINECRAFT_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial,
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["action_iteration"] == 161
    assert result.value["completed_tasks"][-1] == "Mine 1 stone"
    assert agents.calls.count("voyager.curriculum_qa_questions") == 1
    # 3 fixed biome questions + 2 generated questions + the exact task-context
    # question after curriculum proposes "Mine 1 stone".
    assert agents.calls.count("voyager.curriculum_qa") == 6
    assert agents.calls.count("voyager.curriculum") == 1
    assert "Question 1:" in agents.curriculum_message
    assert "Nearby blocks:" in agents.curriculum_message

    random_requests = tuple(
        request
        for request in capabilities.requests
        if request.capability_id == "research.random.bernoulli-mask"
    )
    assert len(random_requests) == 1
    assert random_requests[0].payload["probability"] == 0.8
    assert "context" in random_requests[0].payload["items"]

    qa_machine_id = (
        "method:voyager:curriculum:voyager-curriculum-qa-memory"
    )
    qa_commits = child_journal.commits(qa_machine_id)
    assert qa_commits
    assert qa_commits[-1].program_digest != ""
    assert len(agents.qa_questions) == 6
