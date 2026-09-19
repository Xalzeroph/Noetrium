from __future__ import annotations

from collections.abc import Mapping

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
from noetrium_platform.research.execution.machines.api import ChildResearchHostRegistry
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.reproduction import ReproductionAssetKind
from research.reproductions.optimus1_minecraft.definition import REPRODUCTION
from research.reproductions.optimus1_minecraft.fidelity import (
    OPTIMUS1_REFERENCE_FIDELITY,
)
from research.reproductions.optimus1_minecraft.memory import (
    Optimus1MemoryBinding,
    optimus1_memory_host,
)
from research.reproductions.optimus1_minecraft.program import (
    OPTIMUS1_METHOD_PROGRAM,
    optimus1_method_initial_state,
)


def test_optimus1_neurips2024_fidelity_freezes_hybrid_memory_architecture() -> None:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY

    assert fidelity.venue == "NeurIPS 2024"
    assert fidelity.hybrid_multimodal_memory is True
    assert fidelity.hdkg_enabled is True
    assert fidelity.amep_enabled is True
    assert fidelity.knowledge_guided_planner is True
    assert fidelity.experience_driven_reflector is True
    assert fidelity.action_controller == "steve1"

    assert fidelity.hdkg_source == "minecraft_recipe_dependency_graph"
    assert fidelity.hdkg_retrieval == "goal_conditioned_subgraph_compile"
    assert fidelity.amep_plan_memory is True
    assert fidelity.amep_reflection_memory is True
    assert fidelity.amep_replan_memory is True
    assert fidelity.amep_reflection_labels == (
        "done",
        "continue",
        "replan",
    )
    assert fidelity.reflection_is_multimodal is True
    assert fidelity.replan_uses_error_conditioned_experience is True


def test_optimus1_preserves_paper_release_benchmark_identity_delta() -> None:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY

    assert fidelity.paper_long_horizon_task_count == 67
    assert fidelity.official_release_config_task_count == 73
    assert fidelity.paper_task_group_count == 7
    assert fidelity.reported_metrics == (
        "success_rate",
        "average_steps",
        "average_time",
    )
    assert set(fidelity.headline_groups) == {
        "iron",
        "gold",
        "diamond",
        "redstone",
        "armor",
    }
    assert fidelity.official_release_planner_model == "gpt-4o"
    assert fidelity.official_release_controller_checkpoint == "steve1"


def test_optimus1_reproduction_keeps_unresolved_paper_cut_explicit() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    assert REPRODUCTION.identity.method_id == "optimus1-minecraft"
    assert REPRODUCTION.catalog.benchmark_ids == ()
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind("fidelity") in kinds
    assert ReproductionAssetKind("research_program") in kinds
    assert ReproductionAssetKind("method_program") in kinds
    assert REPRODUCTION.primary_executable == (
        "research/reproductions/optimus1_minecraft/program.py"
    )
    assert any(
        "67-task" in delta.description and "73" in delta.description
        for delta in REPRODUCTION.deltas
    )


class _OptimusRetrieval:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({"fixture": "optimus1-retrieval"})

    def best_match(self, query: str, choices: tuple[str, ...]):
        del query
        return choices[0] if choices else None

    def choose_reflection(
        self,
        *,
        task_key: str,
        environment: str,
        category: str,
        candidates: tuple[dict, ...],
    ) -> int:
        del task_key, environment, category
        assert candidates
        return 0


class _OptimusGraph:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({"fixture": "optimus1-graph"})

    def compile(self, goal: str, number: int = 1) -> str:
        return f"{goal}:{number}"


class _OptimusAgents:
    def __init__(self) -> None:
        self.planner_calls = 0
        self.reflector_calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "optimus1.retrieval":
            return MethodAgentResult(
                value={
                    "goal": "log",
                    "visual_info": "hotbar empty",
                    "environment": "forest",
                }
            )
        if request.agent_id == "optimus1.planner":
            self.planner_calls += 1
            return MethodAgentResult(
                value={
                    "planning": (
                        {"task": "mine log", "goal": ("log", 1)},
                    )
                }
            )
        if request.agent_id == "optimus1.reflector":
            self.reflector_calls += 1
            assert request.view["environment_steps"] == 1200
            return MethodAgentResult(
                value={"category": "replan", "environment": "forest"}
            )
        raise AssertionError(
            f"unexpected Optimus-1 agent: {request.agent_id}"
        )


class _OptimusMinecraft:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "environment.act"
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            effect_class=EffectClass.RECONCILABLE,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        call = len(self.requests)
        payload = (
            {
                "environment_steps": 1200,
                "subgoal_success": False,
                "task_success": False,
                "game_over": False,
                "observation": {"frame": 1200},
                "before_artifact_ref": "artifact:before-1200",
                "after_artifact_ref": "artifact:after-1200",
                "provider_receipt": {"call": call},
            }
            if call == 1
            else {
                "environment_steps": 1,
                "subgoal_success": True,
                "task_success": False,
                "game_over": False,
                "observation": {"frame": 1201},
                "provider_receipt": {"call": call},
            }
        )
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload=payload,
            generation=f"optimus1-env-{call}",
            effect=EffectReceipt(
                effect_id=f"optimus1-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def _optimus_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="optimus1-method-run",
        trace_id="optimus1-trace",
        span_id="optimus1-span",
        task_id="obtain-log",
    )


def _optimus_children(journal: InMemoryMachineJournal):
    registry = ChildResearchHostRegistry()
    registry.register_static(
        optimus1_memory_host(journal=journal),
        Optimus1MemoryBinding(_OptimusRetrieval(), _OptimusGraph()),
    )
    return registry.executor()


def test_optimus1_method_program_exposes_source_faithful_control_graph() -> None:
    program = OPTIMUS1_METHOD_PROGRAM
    node_ids = tuple(node.node_id for node in program.graph.nodes)
    for required in (
        "retrieval",
        "load_memory",
        "planner",
        "select_subgoal",
        "execute_helper",
        "execute_controller",
        "prepare_reflection",
        "reflector",
        "prepare_replan_context",
        "replan",
        "persist_plan",
        "return",
    ):
        assert required in node_ids

    assert program.required_capabilities == ("environment.act",)
    assert program.graph.node("reflector").max_visits == 64
    assert program.graph.node("execute_controller").max_visits == 32768


def test_optimus1_released_lane_records_periodic_replan_reflection_without_branching() -> None:
    journal = InMemoryMachineJournal()
    agents = _OptimusAgents()
    environment = _OptimusMinecraft()

    result = UniversalMethodMachine(max_steps=200).run(
        OPTIMUS1_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            _optimus_context(),
            capabilities=environment,
            agent_loop=agents,
            child_machines=_optimus_children(journal),
        ),
        initial_state=optimus1_method_initial_state(
            task_id="obtain-log",
            task="obtain one log",
            initial_observation={"frame": 0},
            max_environment_steps=5000,
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED, (
        result.failure_code,
        result.failure_phase,
        result.failure,
        result.diagnostics,
    )
    assert result.value["success"] is True
    assert result.value["environment_steps"] == 1201
    assert result.value["completed_plan_steps"] == 1
    assert result.value["reflection_count"] == 1
    assert result.value["replan_count"] == 0
    assert agents.planner_calls == 1
    assert agents.reflector_calls == 1
    assert len(environment.requests) == 2
    assert len(result.value["trajectory"]) == 2
    assert result.value["memory_write_digest"]
    assert journal.commits(
        "method:optimus1-method-run:optimus1-hybrid-memory"
    )
