from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineExecution,
    ChildResearchMachineRequest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import VIDEOAGENT_REFERENCE_FIDELITY
from .memory import (
    VIDEOAGENT_MEMORY_PROGRAM,
    VideoAgentMemoryBundle,
    videoagent_memory_initial_data,
)
from .source import VIDEOAGENT_AUDITED_COMMIT


_MAIN_AGENT_ID = "videoagent.main-react"
_OBJECT_AGENT_ID = "videoagent.object-memory-react"
_VQA_AGENT_ID = "videoagent.visual-question-answering"
_MEMORY_HOST_ID = "videoagent.structured-video-memory"


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    result = value.strip()
    if not allow_empty and not result:
        raise ValueError(f"{field_name} must be non-empty text")
    return result


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must be an object")
    return decoded


def _sequence(value: object, field_name: str) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError(f"{field_name} must be a sequence")
    rows: list[JsonObject] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError(f"{field_name} rows must be objects")
        rows.append(row)
    return tuple(rows)


def _blob_payload(ref: ArtifactBlobRef) -> JsonObject:
    return {
        "content_sha256": ref.content_sha256,
        "size_bytes": ref.size_bytes,
        "media_type": ref.media_type,
    }


def _blob_ref(value: object, field_name: str) -> ArtifactBlobRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return ArtifactBlobRef(
        content_sha256=_text(
            value.get("content_sha256"),
            f"{field_name}.content_sha256",
        ),
        size_bytes=value.get("size_bytes"),
        media_type=_text(
            value.get("media_type"),
            f"{field_name}.media_type",
        ),
    )


@dataclass(frozen=True, slots=True)
class VideoAgentDecision:
    kind: str
    thought: str = ""
    tool: str | None = None
    arguments: JsonObject = field(default_factory=dict)
    answer: str | None = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _text(self.kind, "VideoAgent decision kind")
        if kind not in {"tool", "final"}:
            raise ValueError(
                "VideoAgent decision kind must be tool or final"
            )
        object.__setattr__(self, "kind", kind)
        if type(self.thought) is not str:
            raise TypeError("VideoAgent thought must be text")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("VideoAgent arguments must be an object")
        object.__setattr__(self, "arguments", freeze_json(self.arguments))
        if kind == "tool":
            if self.tool is None:
                raise ValueError("VideoAgent tool decision requires tool")
            object.__setattr__(
                self,
                "tool",
                _text(self.tool, "VideoAgent tool"),
            )
            if self.answer is not None:
                raise ValueError(
                    "VideoAgent tool decision cannot carry final answer"
                )
        else:
            if self.tool is not None:
                raise ValueError(
                    "VideoAgent final decision cannot carry tool"
                )
            object.__setattr__(
                self,
                "answer",
                _text(self.answer, "VideoAgent final answer"),
            )
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest(self.payload(include_digest=False)),
        )

    def payload(self, *, include_digest: bool = True) -> JsonObject:
        payload: JsonObject = {
            "kind": self.kind,
            "thought": self.thought,
            "tool": self.tool,
            "arguments": thaw_json(self.arguments),
            "answer": self.answer,
        }
        if include_digest:
            payload["decision_digest"] = self.decision_digest
        return payload

    @classmethod
    def from_payload(cls, value: object) -> "VideoAgentDecision":
        row = _mapping(value, "VideoAgent decision")
        decision = cls(
            kind=row.get("kind"),
            thought=str(row.get("thought", "")),
            tool=row.get("tool"),
            arguments=row.get("arguments", {}),
            answer=row.get("answer"),
        )
        supplied = row.get("decision_digest")
        if supplied is not None and require_sha256(
            supplied,
            "VideoAgent decision_digest",
        ) != decision.decision_digest:
            raise ValueError("VideoAgent decision digest mismatch")
        return decision


@dataclass(frozen=True, slots=True)
class VideoAgentReasoningRequest:
    scope: str
    question: str
    scratchpad: tuple[JsonObject, ...]
    tools: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.scope not in {"main", "object"}:
            raise ValueError("VideoAgent reasoner scope is invalid")
        object.__setattr__(
            self,
            "question",
            _text(self.question, "VideoAgent question"),
        )
        if type(self.scratchpad) is not tuple:
            raise TypeError("VideoAgent scratchpad must be a tuple")
        if type(self.tools) is not tuple or not self.tools:
            raise ValueError("VideoAgent tool set must be non-empty")


@runtime_checkable
class VideoAgentReasonerPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def decide(
        self,
        request: VideoAgentReasoningRequest,
        context: ExecutionContext,
    ) -> VideoAgentDecision: ...


@dataclass(frozen=True, slots=True)
class VideoAgentVQARequest:
    question: str
    segment_id: int
    video_ref: ArtifactBlobRef
    backend: str
    neighbor_radius_segments: int
    segment_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question",
            _text(self.question, "VideoAgent VQA question"),
        )
        if type(self.segment_id) is not int or self.segment_id < 0:
            raise ValueError("VideoAgent VQA segment_id must be non-negative")
        if not isinstance(self.video_ref, ArtifactBlobRef):
            raise TypeError("VideoAgent VQA requires video ArtifactBlobRef")
        object.__setattr__(
            self,
            "backend",
            _text(self.backend, "VideoAgent VQA backend"),
        )
        if type(self.neighbor_radius_segments) is not int or (
            self.neighbor_radius_segments < 0
        ):
            raise ValueError("VideoAgent VQA neighbor radius is invalid")
        if type(self.segment_seconds) is not int or self.segment_seconds < 1:
            raise ValueError("VideoAgent segment_seconds must be positive")


@runtime_checkable
class VideoAgentVQAPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def answer(
        self,
        request: VideoAgentVQARequest,
        context: ExecutionContext,
    ) -> str: ...


class VideoAgentAgentLoop:
    """Typed paper-agent seam for the main/object ReAct loops and VQA tool."""

    def __init__(
        self,
        *,
        reasoner: VideoAgentReasonerPort,
        vqa: VideoAgentVQAPort,
    ) -> None:
        if not isinstance(reasoner, VideoAgentReasonerPort):
            raise TypeError("VideoAgent requires VideoAgentReasonerPort")
        if not isinstance(vqa, VideoAgentVQAPort):
            raise TypeError("VideoAgent requires VideoAgentVQAPort")
        self._reasoner = reasoner
        self._vqa = vqa
        require_sha256(
            reasoner.identity_digest,
            "VideoAgent reasoner identity_digest",
        )
        require_sha256(
            vqa.identity_digest,
            "VideoAgent VQA identity_digest",
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "source_commit": VIDEOAGENT_AUDITED_COMMIT,
            "reasoner_identity_digest": self._reasoner.identity_digest,
            "vqa_identity_digest": self._vqa.identity_digest,
            "langchain_version": VIDEOAGENT_REFERENCE_FIDELITY.langchain_version,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id in {_MAIN_AGENT_ID, _OBJECT_AGENT_ID}:
            scope = (
                "main"
                if request.agent_id == _MAIN_AGENT_ID
                else "object"
            )
            tools = (
                VIDEOAGENT_REFERENCE_FIDELITY.main_tools
                if scope == "main"
                else VIDEOAGENT_REFERENCE_FIDELITY.object_memory_tools
            )
            decision = self._reasoner.decide(
                VideoAgentReasoningRequest(
                    scope=scope,
                    question=_text(
                        request.view.get("question"),
                        f"VideoAgent {scope} question",
                    ),
                    scratchpad=_sequence(
                        request.view.get("scratchpad", ()),
                        f"VideoAgent {scope} scratchpad",
                    ),
                    tools=tools,
                ),
                request.context,
            )
            if not isinstance(decision, VideoAgentDecision):
                raise TypeError(
                    "VideoAgent reasoner must return VideoAgentDecision"
                )
            return MethodAgentResult(value=decision.payload())

        if request.agent_id == _VQA_AGENT_ID:
            answer = self._vqa.answer(
                VideoAgentVQARequest(
                    question=_text(
                        request.view.get("question"),
                        "VideoAgent VQA question",
                    ),
                    segment_id=request.view.get("segment_id"),
                    video_ref=_blob_ref(
                        request.view.get("video_ref"),
                        "VideoAgent video_ref",
                    ),
                    backend=_text(
                        request.view.get("backend"),
                        "VideoAgent VQA backend",
                    ),
                    neighbor_radius_segments=request.view.get(
                        "neighbor_radius_segments"
                    ),
                    segment_seconds=request.view.get("segment_seconds"),
                ),
                request.context,
            )
            return MethodAgentResult(
                value={
                    "answer": _text(
                        answer,
                        "VideoAgent VQA answer",
                    )
                }
            )

        raise ValueError(
            f"unexpected VideoAgent agent id: {request.agent_id}"
        )


def videoagent_initial_state(
    *,
    question: str,
    memory_bundle: VideoAgentMemoryBundle,
    video_ref: ArtifactBlobRef,
) -> JsonObject:
    if not isinstance(memory_bundle, VideoAgentMemoryBundle):
        raise TypeError(
            "VideoAgent initial state requires VideoAgentMemoryBundle"
        )
    if not isinstance(video_ref, ArtifactBlobRef):
        raise TypeError(
            "VideoAgent initial state requires video ArtifactBlobRef"
        )
    return {
        "source_commit": VIDEOAGENT_AUDITED_COMMIT,
        "question": _text(question, "VideoAgent question"),
        "memory_bundle": memory_bundle.payload(),
        "video_ref": _blob_payload(video_ref),
        "main_scratchpad": (),
        "main_iterations": 0,
        "pending_main_decision": None,
        "pending_tool": "",
        "pending_arguments": {},
        "pending_thought": "",
        "object_question": "",
        "object_scratchpad": (),
        "object_iterations": 0,
        "pending_object_decision": None,
        "pending_object_tool": "",
        "pending_object_arguments": {},
        "pending_object_thought": "",
        "final_answer": "",
        "forced_stop": False,
        "last_observation": None,
    }


def _main_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "question": request.state.get("question"),
        "scratchpad": request.state.get("main_scratchpad", ()),
        "tool_names": VIDEOAGENT_REFERENCE_FIDELITY.main_tools,
        "segment_seconds": VIDEOAGENT_REFERENCE_FIDELITY.segment_seconds,
        "object_memory_available": True,
        "vqa_hallucination_warning": True,
        "argument_string_quote": "double",
    }


def _object_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "question": request.state.get("object_question"),
        "scratchpad": request.state.get("object_scratchpad", ()),
        "tool_names": VIDEOAGENT_REFERENCE_FIDELITY.object_memory_tools,
        "database_tables": (
            "Objects(object_id, category)",
            "Segments(segment_id)",
            "Objects_Segments(object_id, segment_id)",
        ),
        "insufficient_information_answer": (
            "I cannot answer this question."
        ),
    }


def _vqa_view(request: MethodNodeRequest) -> JsonObject:
    arguments = _mapping(
        request.state.get("pending_arguments", {}),
        "VideoAgent pending VQA arguments",
    )
    return {
        "question": _text(
            arguments.get("question"),
            "VideoAgent VQA question",
        ),
        "segment_id": arguments.get("segment_id"),
        "video_ref": request.state.get("video_ref"),
        "backend": VIDEOAGENT_REFERENCE_FIDELITY.default_vqa_backend,
        "neighbor_radius_segments": (
            VIDEOAGENT_REFERENCE_FIDELITY.vqa_neighbor_radius_segments
        ),
        "segment_seconds": VIDEOAGENT_REFERENCE_FIDELITY.segment_seconds,
    }


def _decision(request: MethodNodeRequest) -> VideoAgentDecision:
    return VideoAgentDecision.from_payload(request.previous_value)


def _route_main_decision(request: MethodNodeRequest) -> MethodNodeResult:
    decision = _decision(request)
    if decision.kind == "final":
        return MethodNodeResult(
            value=decision.payload(),
            state_update={
                "pending_main_decision": decision.payload(),
                "final_answer": decision.answer,
            },
            next_node="return",
        )

    tool = decision.tool
    if tool not in VIDEOAGENT_REFERENCE_FIDELITY.main_tools:
        raise ValueError(f"unsupported VideoAgent main tool: {tool}")
    arguments = _mapping(
        decision.arguments,
        "VideoAgent main tool arguments",
    )
    next_by_tool = {
        "caption_retrieval": "caption_memory",
        "segment_localization": "segment_memory",
        "visual_question_answering": "vqa",
        "object_memory_querying": "start_object_memory",
    }
    return MethodNodeResult(
        value=decision.payload(),
        state_update={
            "pending_main_decision": decision.payload(),
            "pending_tool": tool,
            "pending_arguments": arguments,
            "pending_thought": decision.thought,
        },
        next_node=next_by_tool[tool],
    )


def _require_child(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "VideoAgent requires journal-backed child MemoryMachine"
        )


def _memory_step(
    request: MethodNodeRequest,
    *,
    kind: str,
    payload: JsonObject,
    suffix: str,
) -> ChildResearchMachineExecution:
    _require_child(request)
    bundle = VideoAgentMemoryBundle.from_payload(
        request.state.get("memory_bundle")
    )
    child_machine_id = (
        f"{request.parent_machine_id}:videoagent-memory"
    )
    child = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": VIDEOAGENT_AUDITED_COMMIT,
                "program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
                "bundle_digest": bundle.bundle_digest,
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=videoagent_memory_initial_data(bundle),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": kind,
                    "payload": payload,
                    "source": "videoagent-method",
                }
            },
            command_id_prefix=(
                f"{child_machine_id}:{suffix}:"
                f"{request.node_id}:{request.visit}"
            ),
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError(
            "VideoAgent child MemoryMachine returned invalid execution"
        )
    if child.status.value != "runnable":
        raise RuntimeError(
            "VideoAgent child MemoryMachine stopped unexpectedly: "
            f"{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError(
            "VideoAgent child MemoryMachine result must be object"
        )
    return child


def _caption_memory(request: MethodNodeRequest) -> MethodNodeResult:
    arguments = _mapping(
        request.state.get("pending_arguments", {}),
        "VideoAgent caption arguments",
    )
    child = _memory_step(
        request,
        kind="videoagent.memory.caption-range",
        payload={
            "start_segment": arguments.get("start_segment"),
            "end_segment": arguments.get("end_segment"),
        },
        suffix="caption",
    )
    return MethodNodeResult(
        value=child.result,
        next_node="record_main_tool",
        child_links=(child.link,),
    )


def _segment_memory(request: MethodNodeRequest) -> MethodNodeResult:
    arguments = _mapping(
        request.state.get("pending_arguments", {}),
        "VideoAgent localization arguments",
    )
    child = _memory_step(
        request,
        kind="videoagent.memory.segment-localize",
        payload={
            "description": arguments.get("description"),
        },
        suffix="segment-localize",
    )
    return MethodNodeResult(
        value=child.result,
        next_node="record_main_tool",
        child_links=(child.link,),
    )


def _record_main_tool(request: MethodNodeRequest) -> MethodNodeResult:
    rows = list(
        _sequence(
            request.state.get("main_scratchpad", ()),
            "VideoAgent main scratchpad",
        )
    )
    rows.append({
        "thought": request.state.get("pending_thought", ""),
        "tool": request.state.get("pending_tool"),
        "arguments": request.state.get("pending_arguments", {}),
        "observation": thaw_json(request.previous_value),
    })
    current = request.state.get("main_iterations", 0)
    if type(current) is not int or current < 0:
        raise ValueError("VideoAgent main_iterations is invalid")
    iterations = current + 1
    exhausted = (
        iterations
        >= VIDEOAGENT_REFERENCE_FIDELITY.agent_executor_max_iterations
    )
    update: JsonObject = {
        "main_scratchpad": tuple(rows),
        "main_iterations": iterations,
        "last_observation": thaw_json(request.previous_value),
        "pending_tool": "",
        "pending_arguments": {},
        "pending_thought": "",
    }
    if exhausted:
        update.update({
            "forced_stop": True,
            "final_answer": (
                VIDEOAGENT_REFERENCE_FIDELITY
                .agent_executor_forced_output
            ),
        })
    return MethodNodeResult(
        value={
            "main_iterations": iterations,
            "forced_stop": exhausted,
        },
        state_update=update,
        next_node="return" if exhausted else "main_agent",
    )


def _start_object_memory(request: MethodNodeRequest) -> MethodNodeResult:
    arguments = _mapping(
        request.state.get("pending_arguments", {}),
        "VideoAgent object-memory arguments",
    )
    question = _text(
        arguments.get("question"),
        "VideoAgent object-memory question",
    )
    return MethodNodeResult(
        value={"question": question},
        state_update={
            "object_question": question,
            "object_scratchpad": (),
            "object_iterations": 0,
            "pending_object_decision": None,
            "pending_object_tool": "",
            "pending_object_arguments": {},
            "pending_object_thought": "",
        },
        next_node="object_agent",
    )


def _route_object_decision(request: MethodNodeRequest) -> MethodNodeResult:
    decision = _decision(request)
    if decision.kind == "final":
        return MethodNodeResult(
            value={"answer": decision.answer},
            state_update={
                "pending_object_decision": decision.payload(),
                "last_observation": {"answer": decision.answer},
            },
            next_node="record_object_as_main_tool",
        )
    if decision.tool not in (
        VIDEOAGENT_REFERENCE_FIDELITY.object_memory_tools
    ):
        raise ValueError(
            f"unsupported VideoAgent object-memory tool: {decision.tool}"
        )
    arguments = _mapping(
        decision.arguments,
        "VideoAgent object-memory tool arguments",
    )
    return MethodNodeResult(
        value=decision.payload(),
        state_update={
            "pending_object_decision": decision.payload(),
            "pending_object_tool": decision.tool,
            "pending_object_arguments": arguments,
            "pending_object_thought": decision.thought,
        },
        next_node=(
            "object_database"
            if decision.tool == "database_querying"
            else "object_retrieve"
        ),
    )


def _object_database(request: MethodNodeRequest) -> MethodNodeResult:
    arguments = _mapping(
        request.state.get("pending_object_arguments", {}),
        "VideoAgent database arguments",
    )
    child = _memory_step(
        request,
        kind="videoagent.memory.object-database",
        payload={
            "program": arguments.get("program"),
        },
        suffix="object-database",
    )
    return MethodNodeResult(
        value=child.result,
        next_node="record_object_tool",
        child_links=(child.link,),
    )


def _object_retrieve(request: MethodNodeRequest) -> MethodNodeResult:
    arguments = _mapping(
        request.state.get("pending_object_arguments", {}),
        "VideoAgent object retrieval arguments",
    )
    child = _memory_step(
        request,
        kind="videoagent.memory.object-retrieve",
        payload={
            "description": arguments.get("description"),
        },
        suffix="object-retrieve",
    )
    return MethodNodeResult(
        value=child.result,
        next_node="record_object_tool",
        child_links=(child.link,),
    )


def _record_object_tool(request: MethodNodeRequest) -> MethodNodeResult:
    rows = list(
        _sequence(
            request.state.get("object_scratchpad", ()),
            "VideoAgent object scratchpad",
        )
    )
    rows.append({
        "thought": request.state.get("pending_object_thought", ""),
        "tool": request.state.get("pending_object_tool"),
        "arguments": request.state.get("pending_object_arguments", {}),
        "observation": thaw_json(request.previous_value),
    })
    current = request.state.get("object_iterations", 0)
    if type(current) is not int or current < 0:
        raise ValueError("VideoAgent object_iterations is invalid")
    iterations = current + 1
    exhausted = (
        iterations
        >= VIDEOAGENT_REFERENCE_FIDELITY.agent_executor_max_iterations
    )
    update: JsonObject = {
        "object_scratchpad": tuple(rows),
        "object_iterations": iterations,
        "pending_object_tool": "",
        "pending_object_arguments": {},
        "pending_object_thought": "",
    }
    if exhausted:
        update["last_observation"] = {
            "answer": (
                VIDEOAGENT_REFERENCE_FIDELITY
                .agent_executor_forced_output
            )
        }
    return MethodNodeResult(
        value={
            "object_iterations": iterations,
            "forced_stop": exhausted,
        },
        state_update=update,
        next_node=(
            "record_object_as_main_tool"
            if exhausted
            else "object_agent"
        ),
    )


def _record_object_as_main_tool(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    value = _mapping(
        request.state.get("last_observation", {}),
        "VideoAgent object-memory result",
    )
    answer = _text(
        value.get("answer"),
        "VideoAgent object-memory answer",
    )
    return MethodNodeResult(
        value={"answer": answer},
        state_update={
            "last_observation": {"answer": answer},
        },
        next_node="record_main_tool",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    answer = _text(
        request.state.get("final_answer"),
        "VideoAgent final_answer",
    )
    return MethodNodeResult(
        value={
            "source_commit": VIDEOAGENT_AUDITED_COMMIT,
            "answer": answer,
            "forced_stop": request.state.get("forced_stop") is True,
            "main_iterations": request.state.get("main_iterations", 0),
            "main_scratchpad": request.state.get("main_scratchpad", ()),
            "memory_program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
            "memory_machine_id": (
                None
                if request.parent_machine_id is None
                else f"{request.parent_machine_id}:videoagent-memory"
            ),
        }
    )


def build_videoagent_method_program() -> MethodProgram:
    fidelity = VIDEOAGENT_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "paper": (
            "VideoAgent: A Memory-augmented Multimodal Agent "
            "for Video Understanding"
        ),
        "source_commit": VIDEOAGENT_AUDITED_COMMIT,
        "memory_program_digest": VIDEOAGENT_MEMORY_PROGRAM.program_digest,
        "main_tools": fidelity.main_tools,
        "object_memory_tools": fidelity.object_memory_tools,
        "main_reasoner_model": fidelity.main_reasoner_model,
        "object_reasoner_model": fidelity.object_reasoner_model,
        "temperature": fidelity.reasoner_temperature,
        "langchain_version": fidelity.langchain_version,
        "agent_executor_max_iterations": (
            fidelity.agent_executor_max_iterations
        ),
        "agent_executor_early_stopping_method": (
            fidelity.agent_executor_early_stopping_method
        ),
        "default_vqa_backend": fidelity.default_vqa_backend,
        "segment_seconds": fidelity.segment_seconds,
        "vqa_neighbor_radius_segments": (
            fidelity.vqa_neighbor_radius_segments
        ),
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="videoagent-memory",
            implementation_version=VIDEOAGENT_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="videoagent.memory-agent.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    max_iterations = fidelity.agent_executor_max_iterations
    builder = MethodProgramBuilder(identity, entrypoint="main_agent")
    builder.agent(
        "main_agent",
        "videoagent.react.main",
        _MAIN_AGENT_ID,
        ("route_main",),
        view_handler=_main_view,
        max_visits=max_iterations,
    )
    builder.route(
        "route_main",
        "videoagent.react.route-main",
        _route_main_decision,
        (
            "caption_memory",
            "segment_memory",
            "vqa",
            "start_object_memory",
            "return",
        ),
        max_visits=max_iterations,
    )
    builder.compute(
        "caption_memory",
        "videoagent.memory.caption-retrieval",
        _caption_memory,
        ("record_main_tool",),
        max_visits=max_iterations,
    )
    builder.compute(
        "segment_memory",
        "videoagent.memory.segment-localization",
        _segment_memory,
        ("record_main_tool",),
        max_visits=max_iterations,
    )
    builder.agent(
        "vqa",
        "videoagent.tool.visual-question-answering",
        _VQA_AGENT_ID,
        ("record_main_tool",),
        view_handler=_vqa_view,
        max_visits=max_iterations,
        evidence_obligations=("videoagent.vqa-result",),
    )
    builder.compute(
        "start_object_memory",
        "videoagent.object-memory.start",
        _start_object_memory,
        ("object_agent",),
        max_visits=max_iterations,
    )
    nested_budget = max_iterations * max_iterations
    builder.agent(
        "object_agent",
        "videoagent.object-memory.react",
        _OBJECT_AGENT_ID,
        ("route_object",),
        view_handler=_object_view,
        max_visits=nested_budget,
    )
    builder.route(
        "route_object",
        "videoagent.object-memory.route",
        _route_object_decision,
        (
            "object_database",
            "object_retrieve",
            "record_object_as_main_tool",
        ),
        max_visits=nested_budget,
    )
    builder.compute(
        "object_database",
        "videoagent.object-memory.database-query",
        _object_database,
        ("record_object_tool",),
        max_visits=nested_budget,
    )
    builder.compute(
        "object_retrieve",
        "videoagent.object-memory.open-vocabulary-retrieval",
        _object_retrieve,
        ("record_object_tool",),
        max_visits=nested_budget,
    )
    builder.route(
        "record_object_tool",
        "videoagent.object-memory.record-tool",
        _record_object_tool,
        ("object_agent", "record_object_as_main_tool"),
        max_visits=nested_budget,
    )
    builder.compute(
        "record_object_as_main_tool",
        "videoagent.object-memory.return-to-main",
        _record_object_as_main_tool,
        ("record_main_tool",),
        max_visits=max_iterations,
    )
    builder.route(
        "record_main_tool",
        "videoagent.react.record-tool",
        _record_main_tool,
        ("main_agent", "return"),
        max_visits=max_iterations,
    )
    builder.return_node(
        "return",
        "videoagent.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "videoagent.memory.child-cuts",
            "videoagent.react.trajectory",
            "videoagent.vqa-result",
        ),
        metric_names=(
            "main_iterations",
            "forced_stop",
        ),
        artifact_kinds=(
            "videoagent_memory_bundle",
            "videoagent_react_trajectory",
            "videoagent_vqa_observation",
        ),
    )


VIDEOAGENT_METHOD_PROGRAM = build_videoagent_method_program()


__all__ = [
    "VIDEOAGENT_METHOD_PROGRAM",
    "VideoAgentAgentLoop",
    "VideoAgentDecision",
    "VideoAgentReasonerPort",
    "VideoAgentReasoningRequest",
    "VideoAgentVQAPort",
    "VideoAgentVQARequest",
    "build_videoagent_method_program",
    "videoagent_initial_state",
]
