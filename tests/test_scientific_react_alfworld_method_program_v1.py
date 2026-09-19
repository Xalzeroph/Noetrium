from __future__ import annotations

from collections.abc import Mapping

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
)
from noetrium_platform.research.execution.workflow.api import MethodRunStatus, MethodRuntimeContext
from research.reproductions.react_alfworld import (
    REACT_ALFWORLD_METHOD_PROGRAM,
    ReactAlfworldAgentLoop,
    react_alfworld_initial_state,
)


def _context(run_id: str = "react-run") -> ExecutionContext:
    return ExecutionContext(
        run_id=run_id,
        trace_id="trace-1",
        span_id="span-1",
        study_id="react-alfworld",
        task_id="task-1",
        decision_cycle_id="cycle-1",
        participant_generations=(),
    )


class _SequenceModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def complete(self, prompt: str, context: ExecutionContext) -> str:
        assert context.run_id == "react-run"
        self.prompts.append(prompt)
        if not self.outputs:
            raise AssertionError("model output sequence exhausted")
        return self.outputs.pop(0)


class _AlwaysThinkModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, context: ExecutionContext) -> str:
        del prompt, context
        self.calls += 1
        return f"think: step {self.calls}"


class _EnvironmentCapability:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "environment.act",
            "1",
            "noetrium.environment.action-capability.request.v1",
            "noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "environment.act"
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        assert request.payload["action_type"] == "command"
        action = request.payload["payload"]["text"]
        assert isinstance(action, str)
        is_terminal = action == "open fridge"
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"obs-{len(self.requests)}",
                    "generation": f"env-gen-{len(self.requests)}",
                    "payload": {
                        "text": (
                            "The environment reports an invalid think command."
                            if action.startswith("think:")
                            else "The fridge is open."
                        ),
                        "done": is_terminal,
                        "info": {"won": is_terminal},
                    },
                    "artifact_refs": (),
                },
            },
            generation=f"env-gen-{len(self.requests)}",
            effect=EffectReceipt(
                effect_id=f"effect-{len(self.requests)}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_react_method_program_steps_think_then_overrides_visible_observation(tmp_path) -> None:
    model = _SequenceModel(["think: inspect the room", "open fridge"])
    environment = _EnvironmentCapability()
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=ReactAlfworldAgentLoop(model),
    )

    result = run_method_program(
        REACT_ALFWORLD_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=react_alfworld_initial_state(
            base_prompt="DEMO\n",
            initial_observation="You are in a kitchen.",
        ),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["turns"] == 2
    assert result.value["steps"] == (
        {"action": "think: inspect the room", "observation": "OK."},
        {"action": "open fridge", "observation": "The fridge is open."},
    )
    assert [request.payload["payload"]["text"] for request in environment.requests] == [
        "think: inspect the room",
        "open fridge",
    ]
    assert len(model.prompts) == 2
    assert model.prompts[0] == "DEMO\nYou are in a kitchen.\n>"
    assert "think: inspect the room\nOK.\n>" in model.prompts[1]
    # This direct interpreter run has no Machine transition authority. Method-node
    # checkpoint requests therefore remain acceleration hints and must not create a
    # durable checkpoint that could compete with Journal/Machine execution truth.
    assert result.checkpoint is None


def test_react_method_program_enforces_paper_turn_budget_as_method_semantics(tmp_path) -> None:
    model = _AlwaysThinkModel()
    environment = _EnvironmentCapability()
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=ReactAlfworldAgentLoop(model),
    )

    result = run_method_program(
        REACT_ALFWORLD_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=react_alfworld_initial_state(base_prompt="DEMO\n", initial_observation="Start."),
        state_root=tmp_path / "machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is False
    assert result.value["turns"] == 49
    assert len(result.value["steps"]) == 49
    assert all(step["observation"] == "OK." for step in result.value["steps"])
    assert model.calls == 49
    assert len(environment.requests) == 49
    assert dict(result.visit_counts)["model"] == 49
    assert dict(result.visit_counts)["environment"] == 49
