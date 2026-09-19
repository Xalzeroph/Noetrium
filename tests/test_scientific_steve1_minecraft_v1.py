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
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.reproduction import ReproductionAssetKind

from research.reproductions.steve1_minecraft.definition import REPRODUCTION
from research.reproductions.steve1_minecraft.fidelity import (
    STEVE1_REFERENCE_FIDELITY,
)
from research.reproductions.steve1_minecraft.program import (
    STEVE1_METHOD_PROGRAM,
    Steve1AgentLoop,
    Steve1ControlPrediction,
    Steve1ControlRequest,
    Steve1GoalEmbedding,
    Steve1PromptModality,
    steve1_initial_state,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="steve1-run",
        trace_id="trace-steve1",
        span_id="span-steve1",
        study_id="steve1",
        task_id="look-at-sky",
        decision_cycle_id="cycle-steve1",
    )


class _Controller:
    def __init__(self) -> None:
        self.text_prompts = []
        self.visual_prompts = []
        self.requests: list[Steve1ControlRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "controller": "steve1-fixture",
            "implementation_revision": 1,
        })

    def encode_text(self, prompt, context):
        assert context.run_id == "steve1-run"
        self.text_prompts.append(prompt)
        return Steve1GoalEmbedding(
            Steve1PromptModality.TEXT,
            "sha256:goal-text",
            {"prompt": prompt},
        )

    def encode_visual(self, artifact_ref, context):
        self.visual_prompts.append(artifact_ref)
        return Steve1GoalEmbedding(
            Steve1PromptModality.VISUAL,
            "sha256:goal-visual",
            {"source": artifact_ref},
        )

    def act(self, request, context):
        assert context.task_id == "look-at-sky"
        self.requests.append(request)
        step = request.step_index
        return Steve1ControlPrediction(
            controls={
                "buttons": {
                    "forward": 1 if step == 0 else 0,
                    "jump": 0,
                },
                "camera": [0.0, -0.25],
            },
            next_controller_state_ref=f"sha256:state-{step + 1}",
            model_receipt={
                "step": step,
                "cond_scale": request.cond_scale,
            },
        )


class _RawControlCapability:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []
        self._descriptor = CapabilityDescriptor(
            "environment.act",
            "1",
            "noetrium.environment.action-capability.request.v1",
            "noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
        )

    def describe(self, capability_id):
        assert capability_id == "environment.act"
        return self._descriptor

    def invoke(self, request):
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        assert request.payload["action_type"] == "minecraft_raw_control"
        payload = request.payload["payload"]
        assert isinstance(payload, Mapping)
        controls = payload["controls"]
        assert isinstance(controls, Mapping)
        call = len(self.requests)
        done = call == 2
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"steve1-obs-{call}",
                    "generation": f"steve1-env-{call}",
                    "payload": {
                        "frame_artifact_ref": f"sha256:frame-{call}",
                        "state": {
                            "inventory": {},
                            "yaw": float(call),
                        },
                        "reward": 1.0,
                        "done": done,
                        "success": done,
                    },
                    "artifact_refs": (f"sha256:frame-{call}",),
                },
            },
            generation=f"steve1-env-{call}",
            effect=EffectReceipt(
                effect_id=f"steve1-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_steve1_protocol_binds_raw_control_method_program() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind.FIDELITY in kinds
    assert ReproductionAssetKind.METHOD_PROGRAM in kinds
    assert REPRODUCTION.primary_executable == (
        "research/reproductions/steve1_minecraft/program.py"
    )
    assert STEVE1_REFERENCE_FIDELITY.prompt_modalities == ("text", "visual")
    assert STEVE1_REFERENCE_FIDELITY.text_cond_scale == 6.0
    assert STEVE1_REFERENCE_FIDELITY.visual_cond_scale == 7.0
    assert STEVE1_REFERENCE_FIDELITY.stochastic_policy_sampling is True


def test_steve1_method_program_externalizes_recurrent_state(
    tmp_path: Path,
) -> None:
    controller = _Controller()
    environment = _RawControlCapability()
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=Steve1AgentLoop(controller),
    )
    initial_state = steve1_initial_state(
        task_id="look-at-sky",
        initial_observation={
            "frame_artifact_ref": "sha256:frame-0",
            "state": {"inventory": {}, "yaw": 0.0},
        },
        prompt_modality=Steve1PromptModality.TEXT,
        text_prompt="look at the sky",
        max_steps=4,
    )

    result = run_method_program(
        STEVE1_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial_state,
        state_root=tmp_path / "steve1-method",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["steps"] == 2
    assert result.value["goal_embedding_ref"] == "sha256:goal-text"
    assert result.value["final_controller_state_ref"] == "sha256:state-2"
    assert len(controller.text_prompts) == 1
    assert controller.text_prompts == ["look at the sky"]
    assert len(controller.requests) == 2
    assert controller.requests[0].controller_state_ref is None
    assert controller.requests[1].controller_state_ref == "sha256:state-1"
    assert controller.requests[0].cond_scale == 6.0
    assert controller.requests[1].cond_scale == 6.0
    assert len(environment.requests) == 2
    assert len(result.value["trajectory"]) == 2


def test_steve1_visual_prompt_selects_paper_guidance_scale() -> None:
    state = steve1_initial_state(
        task_id="visual-fixture",
        initial_observation={
            "frame_artifact_ref": "sha256:frame-0",
            "state": {},
        },
        prompt_modality=Steve1PromptModality.VISUAL,
        visual_prompt_artifact_ref="sha256:prompt-video",
        max_steps=2,
    )
    assert state["cond_scale"] == 7.0
    assert state["text_prompt"] is None
    assert state["visual_prompt_artifact_ref"] == "sha256:prompt-video"
