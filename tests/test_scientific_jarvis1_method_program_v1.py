from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from noetrium.platform import run_method_program
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
    MethodRunStatus,
    MethodRuntimeContext,
)

from research.reproductions.jarvis1_minecraft.memory import (
    Jarvis1MemoryBinding,
    Jarvis1MemoryPlanStep,
    Jarvis1MemoryRecord,
    jarvis1_memory_host,
)
from research.reproductions.jarvis1_minecraft.program import (
    JARVIS1_METHOD_PROGRAM,
    jarvis1_method_initial_state,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="jarvis1-method-run",
        trace_id="trace-jarvis1-method",
        span_id="span-jarvis1-method",
        study_id="jarvis1",
        task_id="painting",
        decision_cycle_id="cycle-jarvis1",
    )


def _record() -> Jarvis1MemoryRecord:
    return Jarvis1MemoryRecord(
        task_id="painting",
        timestamp="2023-08-09 02:27:00",
        status="success",
        image_name="fixture.png",
        init_inventory={"iron_axe": 1},
        plan=(
            Jarvis1MemoryPlanStep(
                goal={"wool": 1},
                skill_type="mine",
                text="wool",
            ),
            Jarvis1MemoryPlanStep(
                goal={"painting": 1},
                skill_type="craft",
                text="painting",
            ),
        ),
    )


class _FixedMemory:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "jarvis1-method-fixed-memory",
            "available": self.available,
        })

    def lookup(self, task_id: str):
        if self.available and task_id == "painting":
            return _record()
        return None


class _ControllerCapability:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "jarvis1.controller.execute",
            "1",
            "jarvis1.controller.request.v1",
            "jarvis1.controller.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id: str):
        assert capability_id == "jarvis1.controller.execute"
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        call = len(self.requests)
        if call == 1:
            subgoal_success = False
            task_success = False
            steps = 2
        elif call == 2:
            subgoal_success = True
            task_success = False
            steps = 3
        else:
            subgoal_success = True
            task_success = True
            steps = 4
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="jarvis1.controller.execute",
            payload={
                "subgoal_success": subgoal_success,
                "task_success": task_success,
                "environment_steps": steps,
                "agent_state": {
                    "inventory": {
                        "wool": 1 if call >= 2 else 0,
                        "painting": 1 if task_success else 0,
                    },
                    "attempt": call,
                },
                "controller_receipt": {
                    "call": call,
                    "skill_type": request.payload["skill_type"],
                },
            },
            generation=f"jarvis1-controller-{call}",
            effect=EffectReceipt(
                effect_id=f"jarvis1-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def _children(journal: InMemoryMachineJournal, *, available: bool = True):
    registry = ChildResearchHostRegistry()
    registry.register_static(
        jarvis1_memory_host(journal=journal),
        Jarvis1MemoryBinding(_FixedMemory(available=available)),
    )
    return registry.executor()


def test_jarvis1_public_offline_method_retries_subgoal_then_advances(
    tmp_path: Path,
) -> None:
    journal = InMemoryMachineJournal()
    controller = _ControllerCapability()
    result = run_method_program(
        JARVIS1_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            execution=_context(),
            capabilities=controller,
            child_machines=_children(journal),
        ),
        initial_state=jarvis1_method_initial_state(
            task_id="painting",
            instruction="Obtain painting",
            initial_agent_state={"inventory": {"iron_axe": 1}},
            max_environment_steps=100,
        ),
        state_root=tmp_path / "jarvis1-method",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["outcome"] == "success"
    assert result.value["plan_step_count"] == 2
    assert result.value["completed_plan_steps"] == 2
    assert result.value["controller_attempt_count"] == 3
    assert result.value["environment_steps"] == 9
    assert len(result.value["trajectory"]) == 3
    assert len(controller.requests) == 3

    requests = [request.payload for request in controller.requests]
    assert [row["goal"] for row in requests] == [
        {"wool": 1},
        {"wool": 1},
        {"painting": 1},
    ]
    assert [row["skill_type"] for row in requests] == [
        "mine",
        "mine",
        "craft",
    ]
    assert all(row["controller_timeout"] == 500 for row in requests)
    assert all(row["target_reward"] == 1.0 for row in requests)
    assert result.value["memory_record_digest"] == _record().record_digest
    assert journal.commits("method:jarvis1-method-run:jarvis1-memory")


def test_jarvis1_public_offline_method_fails_closed_without_plan(
    tmp_path: Path,
) -> None:
    journal = InMemoryMachineJournal()
    result = run_method_program(
        JARVIS1_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            execution=_context(),
            capabilities=_ControllerCapability(),
            child_machines=_children(journal, available=False),
        ),
        initial_state=jarvis1_method_initial_state(
            task_id="painting",
            instruction="Obtain painting",
            initial_agent_state={"inventory": {}},
            max_environment_steps=100,
        ),
        state_root=tmp_path / "jarvis1-missing-plan",
    )

    assert result.status is MethodRunStatus.FAILED
    assert "online planning is unreleased" in str(result.failure)
