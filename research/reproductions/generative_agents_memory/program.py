from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import GENERATIVE_AGENTS_AUDITED_COMMIT
from .retrieval import GenerativeMemoryNode, retrieve_top

_REFLECTION_AGENT = "generative-agents.reflection"
_PLANNING_AGENT = "generative-agents.planning"
_BEHAVIOR_AGENT = "generative-agents.behavior"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Generative Agents {field} must be text")
    return value


def _vector(value: object, field: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Generative Agents {field} must be a numeric sequence")
    rows = tuple(float(row) for row in value)
    if not rows:
        raise ValueError(f"Generative Agents {field} must be non-empty")
    return rows


def _memory_nodes(value: object) -> tuple[GenerativeMemoryNode, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("Generative Agents memories must be a sequence")
    rows: list[GenerativeMemoryNode] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise TypeError("Generative Agents memory rows must be objects")
        rows.append(
            GenerativeMemoryNode(
                node_id=_text(raw.get("node_id"), "memory node_id"),
                embedding=_vector(raw.get("embedding"), "memory embedding"),
                poignancy=float(raw.get("poignancy", 0.0)),
                last_access_rank=int(raw.get("last_access_rank", 1)),
            )
        )
    return tuple(rows)


def generative_agents_initial_state(
    *,
    agent_id: str,
    observation: str,
    focal_embedding: tuple[float, ...],
    memories: tuple[JsonObject, ...],
) -> JsonObject:
    return {
        "agent_id": _text(agent_id, "agent_id"),
        "observation": _text(observation, "observation"),
        "focal_embedding": focal_embedding,
        "memories": memories,
        "retrieved_memory_ids": (),
        "retrieval_scores": (),
        "reflections": (),
        "plan": "",
        "behavior": "",
    }


def _retrieve(request: MethodNodeRequest) -> MethodNodeResult:
    scores = retrieve_top(
        _memory_nodes(request.state.get("memories", ())),
        focal_embedding=_vector(
            request.state.get("focal_embedding"),
            "focal_embedding",
        ),
    )
    return MethodNodeResult(
        value={
            "retrieved_memory_ids": tuple(row.node.node_id for row in scores),
            "retrieval_scores": tuple(
                {
                    "node_id": row.node.node_id,
                    "recency": row.recency,
                    "relevance": row.relevance,
                    "importance": row.importance,
                    "total": row.total,
                }
                for row in scores
            ),
        },
        state_update={
            "retrieved_memory_ids": tuple(row.node.node_id for row in scores),
            "retrieval_scores": tuple(
                {
                    "node_id": row.node.node_id,
                    "recency": row.recency,
                    "relevance": row.relevance,
                    "importance": row.importance,
                    "total": row.total,
                }
                for row in scores
            ),
        },
    )


def _reflection_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "agent_id": request.state.get("agent_id"),
        "observation": request.state.get("observation"),
        "retrieved_memory_ids": request.state.get("retrieved_memory_ids", ()),
        "retrieval_scores": request.state.get("retrieval_scores", ()),
        "instruction": (
            "synthesize higher-level reflections grounded only in retrieved memories"
        ),
    }


def _record_reflection(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        reflections = (value,)
    elif isinstance(value, Mapping):
        raw = value.get("reflections", ())
        if isinstance(raw, str):
            reflections = (raw,)
        elif isinstance(raw, Sequence):
            reflections = tuple(str(row) for row in raw if str(row).strip())
        else:
            raise TypeError("Generative Agents reflection output must be text sequence")
    else:
        raise TypeError("Generative Agents reflection output must be text or object")
    return MethodNodeResult(
        value={"reflections": reflections},
        state_update={"reflections": reflections},
    )


def _planning_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "agent_id": request.state.get("agent_id"),
        "observation": request.state.get("observation"),
        "retrieved_memory_ids": request.state.get("retrieved_memory_ids", ()),
        "reflections": request.state.get("reflections", ()),
        "instruction": "produce the next behavior plan from current observation and memory",
    }


def _record_plan(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        plan = value
    elif isinstance(value, Mapping):
        plan = value.get("plan", value.get("text", ""))
    else:
        raise TypeError("Generative Agents planning output must be text or object")
    plan = _text(plan, "plan")
    return MethodNodeResult(value={"plan": plan}, state_update={"plan": plan})


def _behavior_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "agent_id": request.state.get("agent_id"),
        "observation": request.state.get("observation"),
        "retrieved_memory_ids": request.state.get("retrieved_memory_ids", ()),
        "reflections": request.state.get("reflections", ()),
        "plan": request.state.get("plan", ""),
        "instruction": "select the next situated behavior",
    }


def _record_behavior(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        behavior = value
    elif isinstance(value, Mapping):
        behavior = value.get("behavior", value.get("action", value.get("text", "")))
    else:
        raise TypeError("Generative Agents behavior output must be text or object")
    behavior = _text(behavior, "behavior")
    return MethodNodeResult(
        value={"behavior": behavior},
        state_update={"behavior": behavior},
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "agent_id": request.state.get("agent_id"),
            "retrieved_memory_ids": request.state.get("retrieved_memory_ids", ()),
            "reflection_count": len(tuple(request.state.get("reflections", ()))),
            "plan": request.state.get("plan", ""),
            "behavior": request.state.get("behavior", ""),
        }
    )


def build_generative_agents_method_program(
    *,
    enable_reflection: bool = True,
    enable_planning: bool = True,
) -> MethodProgram:
    if type(enable_reflection) is not bool or type(enable_planning) is not bool:
        raise TypeError("Generative Agents ablation flags must be boolean")

    configuration: JsonObject = {
        "source_commit": GENERATIVE_AGENTS_AUDITED_COMMIT,
        "retrieval": "recency+relevance+importance",
        "enable_reflection": enable_reflection,
        "enable_planning": enable_planning,
        "population_protocol": 25,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="generative-agents",
            implementation_version=GENERATIVE_AGENTS_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="generative-agents.uist2023.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    after_retrieve = (
        "reflection"
        if enable_reflection
        else "planning"
        if enable_planning
        else "behavior"
    )
    builder = MethodProgramBuilder(identity, entrypoint="retrieve")
    builder.compute(
        "retrieve",
        "generative-agents.memory.retrieve",
        _retrieve,
        (after_retrieve,),
    )
    if enable_reflection:
        next_node = "planning" if enable_planning else "behavior"
        builder.agent(
            "reflection",
            "generative-agents.memory.reflect",
            _REFLECTION_AGENT,
            ("record_reflection",),
            view_handler=_reflection_view,
        )
        builder.compute(
            "record_reflection",
            "generative-agents.memory.record-reflection",
            _record_reflection,
            (next_node,),
        )
    if enable_planning:
        builder.agent(
            "planning",
            "generative-agents.plan",
            _PLANNING_AGENT,
            ("record_plan",),
            view_handler=_planning_view,
        )
        builder.compute(
            "record_plan",
            "generative-agents.plan.record",
            _record_plan,
            ("behavior",),
        )
    builder.agent(
        "behavior",
        "generative-agents.behavior",
        _BEHAVIOR_AGENT,
        ("record_behavior",),
        view_handler=_behavior_view,
    )
    builder.compute(
        "record_behavior",
        "generative-agents.behavior.record",
        _record_behavior,
        ("return",),
    )
    builder.return_node("return", "generative-agents.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "generative-agents.memory-retrieval",
            "generative-agents.reflection",
            "generative-agents.plan",
            "generative-agents.behavior",
        ),
        metric_names=(
            "believability_score",
            "reflection_count",
            "model_call_count",
        ),
        artifact_kinds=(
            "generative_agents_memory_projection",
            "generative_agents_behavior_trace",
        ),
    )


GENERATIVE_AGENTS_METHOD_PROGRAM = build_generative_agents_method_program()

__all__ = [
    "GENERATIVE_AGENTS_METHOD_PROGRAM",
    "build_generative_agents_method_program",
    "generative_agents_initial_state",
]
