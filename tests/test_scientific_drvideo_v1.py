from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.benchmarks.egoschema import (
    EGOSCHEMA_PUBLIC_COUNT,
    EGOSCHEMA_PUBLIC_SPLIT,
    EgoSchemaTaskRecord,
)
from research.reproductions.drvideo.benchmark import (
    build_drvideo_egoschema_public_cut,
)
from research.reproductions.drvideo.fidelity import DRVIDEO_REFERENCE_FIDELITY
from research.reproductions.drvideo.program import (
    DRVIDEO_METHOD_PROGRAM,
    drvideo_initial_state,
)
from research.reproductions.drvideo.study import (
    DRVIDEO_EGOSCHEMA_AGENT_MODEL,
    DRVIDEO_EGOSCHEMA_CAPTIONER,
    DRVIDEO_EGOSCHEMA_SAMPLING_FPS,
    build_drvideo_egoschema_public_study,
    drvideo_egoschema_trial_protocol,
)


def test_drvideo_cvpr2025_fidelity_freezes_document_agent_pipeline() -> None:
    fidelity = DRVIDEO_REFERENCE_FIDELITY

    assert fidelity.venue == "CVPR 2025"
    assert fidelity.video_document_conversion is True
    assert fidelity.text_space_semantic_retrieval is True
    assert fidelity.question_conditioned_augmentation is True
    assert fidelity.multi_stage_agent_loop is True
    assert fidelity.chain_of_thought_answering is True

    assert fidelity.paper_initial_top_k == 5
    assert fidelity.official_code_initial_top_k == 20
    assert fidelity.max_agent_rounds == 2
    assert fidelity.augmentation_types == ("caption", "vqa")
    assert fidelity.maximum_added_frames_per_round == 3

    assert fidelity.egoschema_sampling_fps == 0.5
    assert fidelity.moviechat_sampling_fps == 0.5
    assert fidelity.videomme_sampling_fps == 0.2
    assert fidelity.egoschema_public_task_count == 500

    assert fidelity.egoschema_reported_accuracy == 0.664
    assert fidelity.moviechat_global_reported_accuracy == 0.931
    assert fidelity.moviechat_breakpoint_reported_accuracy == 0.564
    assert fidelity.videomme_long_without_subtitles_accuracy == 0.517
    assert fidelity.videomme_long_with_subtitles_accuracy == 0.717


def test_drvideo_method_program_compiles_explicit_document_agent_loop() -> None:
    program = DRVIDEO_METHOD_PROGRAM

    assert program.program_identity.method.method_id == "drvideo"
    assert program.required_capabilities == ("data.semantic-similarity",)
    assert tuple(node.node_id for node in program.graph.nodes) == (
        "prepare_retrieval",
        "retrieve",
        "record_retrieval",
        "initial_augment",
        "record_initial_augment",
        "planning",
        "route_planning",
        "interaction",
        "record_interaction",
        "augment",
        "record_augment",
        "answer",
        "record_answer",
        "return",
    )
    assert program.graph.node("planning").max_visits == 2
    assert program.graph.node("interaction").max_visits == 2
    assert program.graph.node("augment").max_visits == 2



class _DrVideoSemanticCapability:
    def __init__(self, document: tuple[dict, ...]) -> None:
        self.document = {row["frame_id"]: row for row in document}
        self.requests: list[CapabilityRequest] = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "data.semantic-similarity"
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            EffectClass.PURE,
            True,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        assert request.capability_id == "data.semantic-similarity"
        self.requests.append(request)
        assert request.payload["limit"] == 2
        matches = tuple(
            {
                "source_id": "drvideo-document",
                "record_id": frame_id,
                "content_digest": self.document[frame_id]["content_digest"],
                "score": score,
                "rank": rank,
            }
            for rank, (frame_id, score) in enumerate(
                (("frame-0", 0.99), ("frame-1", 0.91)),
                start=1,
            )
        )
        return CapabilityResult(
            request.capability_id,
            {
                "projection_digest": request.payload["projection_digest"],
                "source_cut_digest": request.payload["source_cut_digest"],
                "embedding_model_digest": request.payload["embedding_model_digest"],
                "metric": "cosine_similarity",
                "candidate_count": len(self.document),
                "matches": matches,
            },
        )


class _DrVideoAgents:
    def __init__(self) -> None:
        self.planning_calls = 0
        self.views: list[tuple[str, dict]] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        view = dict(request.view)
        self.views.append((request.agent_id, view))

        if request.agent_id == "drvideo.visual-augmenter":
            updates = tuple(
                {
                    "frame_id": row["frame_id"],
                    "type": row["type"],
                    "text": (
                        f"question-specific evidence for {row['frame_id']}"
                        if row["type"] == "vqa"
                        else f"dense caption for {row['frame_id']}"
                    ),
                }
                for row in view["requests"]
            )
            return MethodAgentResult(value={"updates": updates})

        if request.agent_id == "drvideo.planning-agent":
            self.planning_calls += 1
            if self.planning_calls == 1:
                return MethodAgentResult(
                    value={
                        "confidence": "0",
                        "explanation": "Need a detailed caption for frame-3.",
                    }
                )
            return MethodAgentResult(
                value={
                    "confidence": "1",
                    "explanation": "The augmented document is sufficient.",
                }
            )

        if request.agent_id == "drvideo.interaction-agent":
            assert view["maximum_new_frames"] == 3
            assert "frame-3" not in view["caption_augmented_frame_ids"]
            return MethodAgentResult(
                value={
                    "frames": (
                        {"frame_id": "frame-3", "type": "caption"},
                    )
                }
            )

        if request.agent_id == "drvideo.answering-agent":
            assert view["chain_of_thought"] is True
            return MethodAgentResult(
                value={
                    "answer": "B",
                    "reasoning": "Retrieved and augmented evidence supports B.",
                }
            )

        raise AssertionError(f"unexpected DrVideo agent: {request.agent_id}")


def test_drvideo_method_program_executes_retrieval_feedback_and_answer_loop() -> None:
    document = tuple(
        {
            "frame_id": f"frame-{index}",
            "text": f"coarse document sentence {index}",
            "content_digest": canonical_digest({"frame": index}),
        }
        for index in range(5)
    )
    projection_digest = canonical_digest({"projection": "drvideo-test"})
    source_cut_digest = canonical_digest({"source-cut": "drvideo-test"})
    embedding_model_digest = canonical_digest({"embedding": "drvideo-test"})
    capabilities = _DrVideoSemanticCapability(document)
    agents = _DrVideoAgents()

    result = UniversalMethodMachine(max_steps=80).run(
        DRVIDEO_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext(
                "drvideo-test",
                "trace",
                "span",
                task_id="egoschema:test",
            ),
            capabilities=capabilities,
            agent_loop=agents,
        ),
        initial_state=drvideo_initial_state(
            question="What did the person do after entering the room?",
            options=("A", "B", "C", "D", "E"),
            document=document,
            projection_digest=projection_digest,
            source_cut_digest=source_cut_digest,
            embedding_model_digest=embedding_model_digest,
            retrieval_query_vector=(1.0, 0.0, 0.5),
            top_k=2,
            max_rounds=2,
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED, (
        result.failure_code,
        result.failure_phase,
        result.failure,
        result.diagnostics,
    )
    assert result.value["answer"] == "B"
    assert result.value["interaction_rounds"] == 1
    assert tuple(result.value["retrieved_frame_ids"]) == ("frame-0", "frame-1")
    assert tuple(result.value["vqa_augmented_frame_ids"]) == (
        "frame-0",
        "frame-1",
    )
    assert tuple(result.value["caption_augmented_frame_ids"]) == ("frame-3",)
    assert len(capabilities.requests) == 1
    assert agents.planning_calls == 2
    assert [agent_id for agent_id, _ in agents.views] == [
        "drvideo.visual-augmenter",
        "drvideo.planning-agent",
        "drvideo.interaction-agent",
        "drvideo.visual-augmenter",
        "drvideo.planning-agent",
        "drvideo.answering-agent",
    ]



def _drv_egoschema_record(index: int) -> EgoSchemaTaskRecord:
    return EgoSchemaTaskRecord(
        q_uid=f"drvideo-video-{index:04d}",
        question=f"What happened in DrVideo fixture {index}?",
        options=(
            f"option-a-{index}",
            f"option-b-{index}",
            f"option-c-{index}",
            f"option-d-{index}",
            f"option-e-{index}",
        ),
        video_content_sha256=canonical_digest({"drvideo-video": index}),
        answer_index=index % 5,
    )


def test_drvideo_egoschema_study_binds_cvpr2025_protocol() -> None:
    benchmark = build_drvideo_egoschema_public_cut(
        tuple(
            _drv_egoschema_record(index)
            for index in range(EGOSCHEMA_PUBLIC_COUNT)
        ),
        questions_content_sha256=canonical_digest(
            {"drvideo-egoschema": "questions"}
        ),
        public_answers_content_sha256=canonical_digest(
            {"drvideo-egoschema": "answers"}
        ),
    )
    protocol = drvideo_egoschema_trial_protocol(benchmark)
    study = build_drvideo_egoschema_public_study(benchmark)

    assert len(benchmark.selected_tasks(EGOSCHEMA_PUBLIC_SPLIT)) == 500
    assert protocol.protocol_id == (
        "drvideo.cvpr2025.egoschema-public.paper-authoritative.v1"
    )
    assert study.trial_protocol_identity == protocol

    method = next(
        row
        for row in study.binding_requirements.participants
        if row.role == "document_retrieval_video_agent"
    )
    assert method.method_id == "drvideo"
    assert method.treatment_id == "cvpr-2025-paper-authoritative"
    assert "data.semantic-similarity" in method.capability_requirement_ids

    assert DRVIDEO_EGOSCHEMA_SAMPLING_FPS == 0.5
    assert DRVIDEO_EGOSCHEMA_CAPTIONER == "lavila"
    assert DRVIDEO_EGOSCHEMA_AGENT_MODEL == "gpt-4-1106-preview"
    assert {
        row.role for row in study.binding_requirements.model_roles
    } == {"agent", "captioner"}
    assert {
        row.measurement_id
        for row in study.measurement_protocol.definitions
    } == {
        "augmented_frame_count",
        "interaction_rounds",
        "multiple_choice_accuracy",
        "retrieved_frame_count",
    }
    assert study.execution_policy.trial_budget.max_model_calls == 8
