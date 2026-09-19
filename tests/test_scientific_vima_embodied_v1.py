from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from noetrium.platform import run_method_program
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.evidence.artifact.content.providers import (
    CanonicalJsonTensorContentStore,
    DirectoryArtifactBlobStore,
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
from research.reproductions.vima_embodied.policy import (
    VimaActionBounds,
    VimaDiscreteAction,
    VimaPolicyAgentLoop,
    VimaPolicyPrediction,
    VimaPolicyRequest,
    de_discretize_vima_action,
)
from research.reproductions.vima_embodied.program import (
    VIMA_METHOD_PROGRAM,
    vima_initial_state,
)


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="vima-run",
        trace_id="trace-vima",
        span_id="span-vima",
        study_id="vima",
        task_id="visual_manipulation",
        decision_cycle_id="cycle-vima",
    )


def _store(root: Path) -> CanonicalJsonTensorContentStore:
    blob = DirectoryArtifactBlobStore(root / "blob")
    return CanonicalJsonTensorContentStore(
        blob,
        blob_store_identity_digest=canonical_digest({
            "provider": "test-vima-blob-store",
            "root": str((root / "blob").resolve()),
        }),
    )


def _ref(store, value, schema):
    return store.put(value, schema_id=schema)


def test_vima_action_postprocess_matches_camera_ready_inference() -> None:
    action = VimaDiscreteAction(
        pose0_position=(25, 50),
        pose0_rotation=(25, 0, 49, 10),
        pose1_position=(49, 99),
        pose1_rotation=(0, 25, 49, 40),
    )
    bounds = VimaActionBounds(
        low=(0.25, -0.5),
        high=(0.75, 0.5),
    )

    decoded = de_discretize_vima_action(action, bounds)

    assert decoded.pose0_position == pytest.approx((0.5, 0.0))
    assert decoded.pose0_rotation == pytest.approx(
        (0.0, -1.0, 0.96, -0.6)
    )
    assert decoded.pose1_position == pytest.approx((0.74, 0.49))
    assert decoded.pose1_rotation == pytest.approx(
        (-1.0, 0.0, 0.96, 0.6)
    )


class _PolicyModel:
    def __init__(self, store) -> None:
        self.store = store
        self.requests: list[VimaPolicyRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "model": "vima-test-policy",
            "implementation_revision": 1,
        })

    def predict(
        self,
        request: VimaPolicyRequest,
        context: ExecutionContext,
    ) -> VimaPolicyPrediction:
        assert context.run_id == "vima-run"
        self.requests.append(request)
        step = request.step_index
        action = (
            VimaDiscreteAction(
                pose0_position=(25, 50),
                pose0_rotation=(25, 25, 25, 25),
                pose1_position=(10, 20),
                pose1_rotation=(10, 10, 10, 10),
            )
            if step == 0
            else VimaDiscreteAction(
                pose0_position=(49, 99),
                pose0_rotation=(49, 49, 49, 49),
                pose1_position=(0, 0),
                pose1_rotation=(0, 0, 0, 0),
            )
        )
        token = _ref(
            self.store,
            ((float(step + 1), 0.5, -0.5),),
            "vima.action-token.tensor.v1",
        )
        return VimaPolicyPrediction(
            action=action,
            action_token_ref=token,
            model_receipt={
                "model_id": "vima-test-policy",
                "step": step,
            },
        )


class _EmbodiedCapability:
    def __init__(self, store) -> None:
        self.store = store
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
        assert request.payload["action_type"] == "embodied_action"
        method_payload = request.payload["payload"]
        assert isinstance(method_payload, Mapping)
        action = method_payload["action"]
        assert isinstance(action, Mapping)

        call = len(self.requests)
        if call == 1:
            assert action["pose0_position"] == pytest.approx((0.5, 0.0))
        token_ref = _ref(
            self.store,
            ((float(call), 0.1), (float(call), 0.2)),
            "vima.observation-token.tensor.v1",
        )
        mask_ref = _ref(
            self.store,
            (True, True),
            "vima.observation-mask.tensor.v1",
        )
        done = call == 2
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"vima-obs-{call}",
                    "generation": f"vima-env-gen-{call}",
                    "payload": {
                        "vima_observation_token_ref": token_ref.payload(),
                        "vima_observation_mask_ref": mask_ref.payload(),
                        "done": done,
                        "success": done,
                        "reward": 1.0 if done else 0.0,
                    },
                    "artifact_refs": (),
                },
            },
            generation=f"vima-env-gen-{call}",
            effect=EffectReceipt(
                effect_id=f"vima-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_vima_method_program_runs_autoregressive_embodied_loop(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    prompt_token = _ref(
        store,
        ((1.0, 0.0), (0.0, 1.0)),
        "vima.prompt-token.tensor.v1",
    )
    prompt_mask = _ref(
        store,
        (True, True),
        "vima.prompt-mask.tensor.v1",
    )
    initial_obs_token = _ref(
        store,
        ((0.1, 0.2), (0.3, 0.4)),
        "vima.observation-token.tensor.v1",
    )
    initial_obs_mask = _ref(
        store,
        (True, True),
        "vima.observation-mask.tensor.v1",
    )
    bounds = VimaActionBounds(
        low=(0.25, -0.5),
        high=(0.75, 0.5),
    )

    model = _PolicyModel(store)
    environment = _EmbodiedCapability(store)
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=VimaPolicyAgentLoop(model),
    )
    initial_state = vima_initial_state(
        task_id="visual_manipulation",
        evaluation_partition="placement_generalization",
        seed=42,
        oracle_max_steps=3,
        prompt_token_ref=prompt_token,
        prompt_mask_ref=prompt_mask,
        initial_observation_token_ref=initial_obs_token,
        initial_observation_mask_ref=initial_obs_mask,
        action_bounds=bounds,
    )

    result = run_method_program(
        VIMA_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial_state,
        state_root=tmp_path / "method-machine",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["done"] is True
    assert result.value["steps"] == 2
    assert result.value["max_steps"] == 5
    assert result.value["observation_count"] == 3
    assert result.value["action_count"] == 2

    assert len(model.requests) == 2
    assert len(model.requests[0].observation_token_refs) == 1
    assert len(model.requests[0].action_token_refs) == 0
    assert len(model.requests[1].observation_token_refs) == 2
    assert len(model.requests[1].action_token_refs) == 1
    assert model.requests[1].step_index == 1
    assert len(environment.requests) == 2
    assert dict(result.visit_counts)["policy"] == 2
    assert dict(result.visit_counts)["environment"] == 2


def test_vima_initial_state_freezes_oracle_plus_bonus_budget(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    state = vima_initial_state(
        task_id="follow_order",
        evaluation_partition="novel_task_generalization",
        seed=7,
        oracle_max_steps=9,
        prompt_token_ref=_ref(
            store,
            ((1.0,),),
            "vima.prompt-token.tensor.v1",
        ),
        prompt_mask_ref=_ref(
            store,
            (True,),
            "vima.prompt-mask.tensor.v1",
        ),
        initial_observation_token_ref=_ref(
            store,
            ((2.0,),),
            "vima.observation-token.tensor.v1",
        ),
        initial_observation_mask_ref=_ref(
            store,
            (True,),
            "vima.observation-mask.tensor.v1",
        ),
        action_bounds=VimaActionBounds(
            low=(0.25, -0.5),
            high=(0.75, 0.5),
        ),
    )

    assert state["max_steps"] == 11
    assert state["step_index"] == 0
    assert state["action_token_refs"] == ()
