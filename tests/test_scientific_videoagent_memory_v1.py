from __future__ import annotations

from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    InMemoryMachineJournal,
    canonical_digest,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchHostRegistry,
    ChildResearchMachineRequest,
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
from research.reproductions.videoagent_memory.fidelity import (
    VIDEOAGENT_REFERENCE_FIDELITY,
)
from research.reproductions.videoagent_memory.memory import (
    VIDEOAGENT_MEMORY_PROGRAM,
    VideoAgentCaption,
    VideoAgentMemoryBinding,
    VideoAgentMemoryBundle,
    VideoAgentSegmentScoreTable,
    videoagent_memory_host,
    videoagent_memory_initial_data,
)
from research.reproductions.videoagent_memory.program import (
    VIDEOAGENT_METHOD_PROGRAM,
    VideoAgentAgentLoop,
    VideoAgentDecision,
    VideoAgentReasoningRequest,
    VideoAgentVQARequest,
    videoagent_initial_state,
)


def _blob(name: str, *, media_type: str = "application/octet-stream"):
    return ArtifactBlobRef(
        canonical_digest({"videoagent-fixture": name}),
        1,
        media_type,
    )


def _bundle() -> VideoAgentMemoryBundle:
    return VideoAgentMemoryBundle(
        video_id="ego:test",
        segment_count=4,
        artifacts=tuple(sorted(
            (
                (name, _blob(name))
                for name in VIDEOAGENT_REFERENCE_FIDELITY.preprocessing_artifacts
            ),
            key=lambda row: row[0],
        )),
        use_reid=True,
    )


class _Index:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "videoagent-index",
            "implementation_revision": 1,
        })

    def captions(self, bundle, start_segment, end_segment):
        captions = (
            "person enters kitchen",
            "person opens microwave",
            "person closes microwave",
            "person leaves kitchen",
        )
        return tuple(
            VideoAgentCaption(segment_id, captions[segment_id])
            for segment_id in range(start_segment, end_segment + 1)
        )

    def segment_scores(self, bundle, description):
        assert description == "microwave"
        return VideoAgentSegmentScoreTable(
            segment_ids=(0, 1, 2, 3),
            textual_scores=(0.0, 1.0, 0.7, 0.0),
            visual_scores=(0.0, 0.8, 1.0, 0.0),
            receipt={"description": description},
        )

    def database_query(self, bundle, program):
        assert "COUNT" in program.upper()
        return {"rows": ((2,),)}

    def retrieve_candidate_objects(self, bundle, description):
        return {"candidate_object_ids": (1, 4), "description": description}


def _children(journal):
    binding = VideoAgentMemoryBinding(_Index())
    registry = ChildResearchHostRegistry()
    registry.register_static(
        videoagent_memory_host(journal=journal),
        binding,
    )
    return registry.executor()


def test_videoagent_memory_preserves_source_caption_quirk_and_18_11_localization() -> None:
    journal = InMemoryMachineJournal()
    children = _children(journal)
    bundle = _bundle()
    machine_id = "memory:videoagent:test"

    caption = children.step_once(
        ChildResearchMachineRequest(
            host_id="videoagent.structured-video-memory",
            parent_machine_id="method:videoagent:test",
            child_machine_id=machine_id,
            instance_identity={
                "bundle_digest": bundle.bundle_digest,
                "program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
            },
            initial_data=videoagent_memory_initial_data(bundle),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": "videoagent.memory.caption-range",
                    "payload": {
                        "start_segment": -9,
                        "end_segment": 99,
                    },
                }
            },
            command_id_prefix="videoagent:caption",
        )
    )
    assert caption.status.value == "runnable"
    assert caption.result["bounded_start"] == 0
    assert caption.result["bounded_end"] == 3
    assert len(caption.result["captions"]) == 4
    assert caption.result["declared_max_caption_count"] == 15
    assert caption.result["source_enforces_declared_limit"] is False

    localized = children.step_once(
        ChildResearchMachineRequest(
            host_id="videoagent.structured-video-memory",
            parent_machine_id="method:videoagent:test",
            child_machine_id=machine_id,
            instance_identity={
                "bundle_digest": bundle.bundle_digest,
                "program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
            },
            initial_data=videoagent_memory_initial_data(bundle),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": "videoagent.memory.segment-localize",
                    "payload": {"description": "microwave"},
                }
            },
            command_id_prefix="videoagent:localize",
        )
    )
    assert localized.status.value == "runnable"
    assert tuple(localized.result["segment_ids"][:2]) == (2, 1)
    assert tuple(localized.result["ensemble_scores"][:2]) == (
        18.0 * 1.0 + 11.0 * 0.7,
        18.0 * 0.8 + 11.0 * 1.0,
    )
    commits = journal.commits(machine_id)
    assert commits
    assert commits[-1].program_digest == VIDEOAGENT_MEMORY_PROGRAM.program_digest


class _Reasoner:
    def __init__(self) -> None:
        self.main_calls = 0
        self.object_calls = 0

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "videoagent-reasoner",
            "implementation_revision": 1,
        })

    def decide(
        self,
        request: VideoAgentReasoningRequest,
        context: ExecutionContext,
    ) -> VideoAgentDecision:
        del context
        if request.scope == "main":
            self.main_calls += 1
            if self.main_calls == 1:
                assert request.scratchpad == ()
                return VideoAgentDecision(
                    "tool",
                    thought="use object memory",
                    tool="object_memory_querying",
                    arguments={"question": "How many people are there?"},
                )
            assert len(request.scratchpad) == 1
            row = request.scratchpad[0]
            assert row["tool"] == "object_memory_querying"
            assert row["arguments"] == {
                "question": "How many people are there?"
            }
            assert row["observation"] == {"answer": "2"}
            return VideoAgentDecision(
                "final",
                thought="done",
                answer="2",
            )

        self.object_calls += 1
        if self.object_calls == 1:
            assert request.scratchpad == ()
            return VideoAgentDecision(
                "tool",
                thought="count people",
                tool="database_querying",
                arguments={
                    "program": (
                        "SELECT COUNT(DISTINCT object_id) FROM Objects "
                        "WHERE category = 'person'"
                    )
                },
            )
        assert len(request.scratchpad) == 1
        assert request.scratchpad[0]["tool"] == "database_querying"
        return VideoAgentDecision(
            "final",
            thought="database has the count",
            answer="2",
        )


class _VQA:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "fixture": "videoagent-vqa",
            "implementation_revision": 1,
        })

    def answer(
        self,
        request: VideoAgentVQARequest,
        context: ExecutionContext,
    ) -> str:
        del request, context
        raise AssertionError("VQA should not be called in object-memory test")


def test_videoagent_method_preserves_nested_object_react_receipts() -> None:
    child_journal = InMemoryMachineJournal()
    children = _children(child_journal)
    agent_loop = VideoAgentAgentLoop(
        reasoner=_Reasoner(),
        vqa=_VQA(),
    )
    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            "videoagent-run",
            "trace",
            "span",
            study_id="videoagent",
            task_id="ego:test",
        ),
        agent_loop=agent_loop,
        child_machines=children,
        runtime_binding_digest=agent_loop.identity_digest,
    )
    runtime = bind_machine_method_runtime(
        VIDEOAGENT_METHOD_PROGRAM,
        runtime,
        machine_id="method:videoagent:test",
    )
    result = UniversalMethodMachine(max_steps=96).run(
        VIDEOAGENT_METHOD_PROGRAM,
        runtime=runtime,
        initial_state=videoagent_initial_state(
            question="How many people are there?",
            memory_bundle=_bundle(),
            video_ref=_blob("video.mp4", media_type="video/mp4"),
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["answer"] == "2"
    assert result.value["forced_stop"] is False
    assert result.value["main_iterations"] == 1
    trajectory = result.value["main_scratchpad"]
    assert len(trajectory) == 1
    assert trajectory[0]["tool"] == "object_memory_querying"
    assert trajectory[0]["arguments"] == {
        "question": "How many people are there?"
    }
    assert trajectory[0]["observation"] == {"answer": "2"}

    memory_machine_id = "method:videoagent:test:videoagent-memory"
    memory_commits = child_journal.commits(memory_machine_id)
    assert memory_commits
    assert any(
        commit.program_digest == VIDEOAGENT_MEMORY_PROGRAM.program_digest
        for commit in memory_commits
    )

    assert runtime.transitions is not None
    parent_commits = runtime.transitions.machine.journal.commits(
        "method:videoagent:test"
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
