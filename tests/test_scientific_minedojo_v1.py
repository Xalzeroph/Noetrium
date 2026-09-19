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
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    TensorContentRef,
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

from research.reproductions.minedojo.benchmark import (
    MINEDOJO_REVISION_ID,
    MineDojoTaskRecord,
    build_minedojo_source,
    build_minedojo_task_set,
)
from research.reproductions.minedojo.definition import REPRODUCTION
from research.reproductions.minedojo.fidelity import (
    MINEDOJO_REFERENCE_FIDELITY,
)
from research.reproductions.minedojo.program import (
    MINEAGENT_METHOD_PROGRAM,
    MineAgentPolicyAgentLoop,
    MineAgentPolicyPrediction,
    MineAgentPolicyRequest,
    mineagent_initial_state,
    project_mineagent_demo_action,
)
from research.reproductions.minedojo.reward import (
    MINECLIP_VIDEO_SCHEMA_ID,
    MineClipRewardBinding,
    MineClipRewardPrediction,
    MineClipRewardRequest,
)
from research.reproductions.minedojo.study import (
    build_minedojo_neurips2022_study,
    minedojo_neurips2022_trial_protocol,
)
from research.reproductions.minedojo.source import (
    MINECLIP_AUDITED_COMMIT,
    MINEDOJO_AUDITED_COMMIT,
)


def _records() -> tuple[MineDojoTaskRecord, ...]:
    rows: list[MineDojoTaskRecord] = []
    for index in range(1581):
        task_id = f"programmatic:{index:04d}"
        rows.append(
            MineDojoTaskRecord(
                task_id=task_id,
                category="programmatic",
                family="harvest",
                prompt=f"programmatic task {index}",
                content_digest=canonical_digest({
                    "task_id": task_id,
                    "category": "programmatic",
                }),
            )
        )
    for index in range(1560):
        task_id = f"creative:{index:04d}"
        rows.append(
            MineDojoTaskRecord(
                task_id=task_id,
                category="creative",
                family="creative",
                prompt=f"creative task {index}",
                content_digest=canonical_digest({
                    "task_id": task_id,
                    "category": "creative",
                }),
            )
        )
    rows.append(
        MineDojoTaskRecord(
            task_id="playthrough",
            category="playthrough",
            family="playthrough",
            prompt="Defeat the Ender Dragon and obtain the dragon egg",
            content_digest=canonical_digest({
                "task_id": "playthrough",
                "category": "playthrough",
            }),
        )
    )
    return tuple(rows)


class _RewardModel:
    def __init__(self, *, revision: int = 1) -> None:
        self._identity_digest = canonical_digest({
            "model": "mineclip-fixture",
            "revision": revision,
        })

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def score(
        self,
        request: MineClipRewardRequest,
    ) -> MineClipRewardPrediction:
        return MineClipRewardPrediction(
            request_digest=request.request_digest,
            similarity_logit=2.75,
            model_identity_digest=self.identity_digest,
            receipt={"fixture": "mineclip"},
        )


def _video(*, frames: int = 16) -> TensorContentRef:
    return TensorContentRef(
        content=ArtifactBlobRef(
            content_sha256=canonical_digest({
                "video": "fixture",
                "frames": frames,
            }),
            size_bytes=frames * 3 * 160 * 256,
            media_type="application/x-minedojo-rgb-tensor",
        ),
        shape=(frames, 3, 160, 256),
        dtype="uint8",
        codec="raw",
        schema_id=MINECLIP_VIDEO_SCHEMA_ID,
    )


def test_minedojo_source_and_fidelity_freeze_paper_consistent_cut() -> None:
    fidelity = MINEDOJO_REFERENCE_FIDELITY
    assert MINEDOJO_AUDITED_COMMIT == (
        "1fc46f58aaeed5eb8018abf030c95a13d41ab4a4"
    )
    assert MINECLIP_AUDITED_COMMIT == (
        "5ec098c1660da44933ae9a221ea3ee180f973e0d"
    )
    assert fidelity.benchmark_task_count == 3142
    assert (
        fidelity.programmatic_task_count,
        fidelity.creative_task_count,
        fidelity.playthrough_task_count,
    ) == (1581, 1560, 1)
    assert fidelity.programmatic_success_aggregation == "any"
    assert fidelity.mineclip_temporal_max_sequence_length == 32
    assert fidelity.mineclip_input_resolution == (160, 256)
    assert fidelity.mineclip_shared_embedding_dim == 512
    assert fidelity.mineclip_pool_variants == ("attn", "avg")


def test_minedojo_benchmark_materialization_requires_complete_cut() -> None:
    records = _records()
    source_digest = canonical_digest({
        "fixture": "minedojo-paper-suite",
        "record_digests": tuple(
            row.content_digest for row in records
        ),
    })
    source = build_minedojo_source(content_digest=source_digest)
    cut = build_minedojo_task_set(
        records,
        source_digest=source_digest,
    )

    assert source.revision_id == MINEDOJO_REVISION_ID
    assert source.metadata["commit"] == MINEDOJO_AUDITED_COMMIT
    assert len(cut.tasks) == 3142
    assert len(cut.selected_tasks("category:programmatic")) == 1581
    assert len(cut.selected_tasks("category:creative")) == 1560
    assert len(cut.selected_tasks("category:playthrough")) == 1
    assert cut.selected_tasks("category:creative")[0].package is not None
    assert (
        cut.selected_tasks("category:creative")[0]
        .package.verifier_requirement_id
        is None
    )
    assert (
        cut.selected_tasks("category:programmatic")[0]
        .package.verifier_requirement_id
        == "benchmark.minedojo.programmatic-state.verifier"
    )

    with pytest.raises(
        ValueError,
        match="requires exactly 3142 tasks",
    ):
        build_minedojo_task_set(
            records[:-1],
            source_digest=source_digest,
        )


def test_mineclip_reward_seam_uses_content_identity_and_raw_similarity_logit() -> None:
    request = MineClipRewardRequest(
        video=_video(frames=16),
        task_prompt="hunt a cow",
        variant="attn",
    )
    binding = MineClipRewardBinding(_RewardModel())
    prediction = binding.score(request)

    assert prediction.similarity_logit == 2.75
    assert prediction.request_digest == request.request_digest
    assert prediction.model_identity_digest == binding.model.identity_digest
    assert len(binding.binding_digest) == 64

    with pytest.raises(
        ValueError,
        match="temporal bound",
    ):
        MineClipRewardRequest(
            video=_video(frames=33),
            task_prompt="hunt a cow",
            variant="attn",
        )


def test_minedojo_reproduction_is_benchmark_first_protocol_bound_lane() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind.BENCHMARK in kinds
    assert ReproductionAssetKind.FIDELITY in kinds
    assert ReproductionAssetKind.SEMANTICS in kinds
    assert ReproductionAssetKind.METHOD_PROGRAM in kinds
    assert ReproductionAssetKind.STUDY in kinds
    assert REPRODUCTION.primary_executable == (
        "research/reproductions/minedojo/program.py"
    )
    assert REPRODUCTION.catalog.benchmark_ids == ("minedojo",)
    assert any(
        "official-registry" in blocker
        or "audited MineDojo runtime image" in blocker
        for blocker in REPRODUCTION.blockers
    )



def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="minedojo-run",
        trace_id="trace-minedojo",
        span_id="span-minedojo",
        study_id="minedojo",
        task_id="fixture-task",
        decision_cycle_id="cycle-minedojo",
    )


class _MineAgentPolicy:
    def __init__(self) -> None:
        self.requests: list[MineAgentPolicyRequest] = []

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "policy": "mineagent-fixture",
            "implementation_revision": 1,
        })

    def predict(
        self,
        request: MineAgentPolicyRequest,
        context: ExecutionContext,
    ) -> MineAgentPolicyPrediction:
        assert context.run_id == "minedojo-run"
        self.requests.append(request)
        return MineAgentPolicyPrediction(
            raw_action=(2, 1, 3, 24, 12, 7),
            model_receipt={
                "fixture": "mineagent",
                "step": request.step_index,
            },
        )


class _MinecraftCapability:
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
        assert request.payload["action_type"] == "minecraft_action"
        payload = request.payload["payload"]
        assert isinstance(payload, Mapping)
        assert tuple(payload["raw_action"]) == (2, 1, 3, 24, 12, 7)
        assert tuple(payload["action"]) == (2, 1, 3, 24, 12, 0, 0, 0)
        call = len(self.requests)
        done = call == 2
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload={
                "accepted": True,
                "observation": {
                    "observation_id": f"minedojo-obs-{call}",
                    "generation": f"minedojo-env-{call}",
                    "payload": {
                        "mineagent_observation": {
                            "compass": (0.0, 0.0, 0.0, 1.0),
                            "gps": (float(call), 64.0, -2.0),
                            "voxels": (0,) * 27,
                            "biome_id": 1,
                            "prev_action": call,
                            "prompt_embedding_ref": "fixture",
                        },
                        "reward": 1.5,
                        "done": done,
                        "success": done,
                    },
                    "artifact_refs": (),
                },
            },
            generation=f"minedojo-env-{call}",
            effect=EffectReceipt(
                effect_id=f"minedojo-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def test_mineagent_released_demo_action_projection_preserves_source_quirk() -> None:
    projected = project_mineagent_demo_action((2, 1, 3, 24, 12, 7))
    assert projected == (2, 1, 3, 24, 12, 0, 0, 0)


def test_mineagent_method_program_runs_deterministic_minecraft_loop(
    tmp_path: Path,
) -> None:
    policy = _MineAgentPolicy()
    environment = _MinecraftCapability()
    runtime = MethodRuntimeContext(
        execution=_context(),
        capabilities=environment,
        agent_loop=MineAgentPolicyAgentLoop(policy),
    )
    initial_state = mineagent_initial_state(
        task_id="fixture-task",
        task_prompt="hunt a spider",
        initial_observation={
            "compass": (0.0, 0.0, 0.0, 1.0),
            "gps": (0.0, 64.0, 0.0),
            "voxels": (0,) * 27,
            "biome_id": 1,
            "prev_action": 0,
            "prompt_embedding_ref": "fixture",
        },
        max_steps=4,
    )

    result = run_method_program(
        MINEAGENT_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=initial_state,
        state_root=tmp_path / "mineagent-method",
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["done"] is True
    assert result.value["steps"] == 2
    assert result.value["cumulative_reward"] == pytest.approx(3.0)
    assert len(result.value["trajectory"]) == 2
    assert len(policy.requests) == 2
    assert policy.requests[1].step_index == 1
    assert len(environment.requests) == 2


def test_minedojo_full_cut_binds_formal_mineagent_study() -> None:
    records = _records()
    source_digest = canonical_digest({
        "fixture": "minedojo-paper-suite",
        "record_digests": tuple(
            row.content_digest for row in records
        ),
    })
    benchmark = build_minedojo_task_set(
        records,
        source_digest=source_digest,
    )

    protocol = minedojo_neurips2022_trial_protocol(benchmark)
    study = build_minedojo_neurips2022_study(benchmark)

    assert protocol.protocol_id == "minedojo.neurips2022.mineagent.v1"
    assert study.benchmark.benchmark_id == "minedojo"
    assert len(study.benchmark.selected_tasks("all")) == 3142
    assert study.method.implementation == "mineagent"
    assert {row.name for row in study.measurements} == {
        "episode_success",
        "episode_steps",
        "cumulative_reward",
        "task_success_rate",
    }
